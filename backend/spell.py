"""Spell-correction для query — Sprint 7 roadmap (вариант B из обсуждения).

SymSpell-like: строим vocab из BM25-корпуса (word → freq), для каждого
out-of-vocab токена в запросе ищем кандидата с edit-distance ≤ 1
(Damerau-Levenshtein: insert/delete/substitute/transpose). Кандидаты
ищутся через precomputed delete-1 index — O(L) на лукап вместо O(V).

Закрывает кейсы Sprint 6 failure analysis: g042 «забыл пороль», g058
«хочу вывыести деньги», g054 «верниите деньги» (последний BM25 уже
тащит, но коррекция даёт буст и bi-encoder'у).

Корректируем только токены длиной ≥ 4 (короткие русские слова часто
омонимичны: «как»/«так», «два»/«дав» — overcorrection-риск). Кандидат
должен встречаться в корпусе ≥ 2 раз — отсекаем typo-в-vocab.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

# Минимальная длина токена для коррекции. Короткие русские слова часто
# омонимичны и edit-1 коррекция даёт false-positive («как»→«кат», и т.п.).
_MIN_WORD_LEN = 4

# Минимальная частота кандидата в корпусе. Отсекает hapax-legomena и
# typo, попавшие в vocab из самих статей (vocab может содержать редкие
# опечатки авторов БЗ — не хотим к ним «корректировать»).
_MIN_CAND_FREQ = 2

# Регэксп для извлечения токенов в запросе. Кириллица + латиница —
# числа/пунктуация остаются в строке как есть (re.sub callback пропускает их).
_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z]+")


def _is_close_d1(a: str, b: str) -> bool:
    """Damerau-Levenshtein distance ≤ 1: insert / delete / substitute / transpose.

    O(min(len(a), len(b))) — быстрее чем полный Wagner-Fischer и достаточно
    для нашего случая (delete-1 index уже отфильтровал дальние кандидаты).
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        i = 0
        while i < la and a[i] == b[i]:
            i += 1
        if i == la:
            return True
        # Substitute: остаток должен совпасть.
        if a[i + 1:] == b[i + 1:]:
            return True
        # Transpose двух соседних символов.
        if (
            i + 1 < la
            and a[i] == b[i + 1]
            and a[i + 1] == b[i]
            and a[i + 2:] == b[i + 2:]
        ):
            return True
        return False
    # Insert / delete: один символ длиннее.
    short, long = (a, b) if la < lb else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1:]


def _deletes_1(word: str) -> Iterator[str]:
    for i in range(len(word)):
        yield word[:i] + word[i + 1:]


class SpellCorrector:
    """SymSpell-like corrector с delete-1 index.

    Vocab — `{word: corpus_frequency}`. Index — `{delete_form: {original_words}}`.
    `correct_word()` возвращает best candidate (edit-distance ≤ 1, max freq) или
    None если коррекция не нужна / не найдена.
    """

    def __init__(
        self,
        vocab_freq: dict[str, int],
        *,
        min_word_len: int = _MIN_WORD_LEN,
        min_cand_freq: int = _MIN_CAND_FREQ,
    ) -> None:
        self._vocab = vocab_freq
        self._min_word_len = min_word_len
        self._min_cand_freq = min_cand_freq
        self._delete_index: dict[str, set[str]] = {}
        for word, freq in vocab_freq.items():
            if len(word) < min_word_len or freq < min_cand_freq:
                continue
            for d in _deletes_1(word):
                self._delete_index.setdefault(d, set()).add(word)

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)

    @property
    def index_size(self) -> int:
        return len(self._delete_index)

    def _candidates(self, word: str) -> set[str]:
        """Кандидаты с edit-distance ≤ 1 через delete-1 lookup (over-permissive,
        фильтруем актуальной distance-проверкой выше)."""
        out: set[str] = set()
        # Vocab word имеет 1 лишний символ vs query (insertion typo в vocab).
        if word in self._delete_index:
            out.update(self._delete_index[word])
        for d in _deletes_1(word):
            # Query имеет 1 лишний символ vs vocab (deletion typo: query → vocab).
            if d in self._vocab and self._vocab[d] >= self._min_cand_freq:
                out.add(d)
            # Substitute или transpose: общая delete-1 форма.
            if d in self._delete_index:
                out.update(self._delete_index[d])
        out.discard(word)
        return out

    def correct_word(self, word: str) -> Optional[str]:
        """Возвращает correction или None (если в vocab / слишком короткое /
        кандидата нет)."""
        if word in self._vocab:
            return None
        if len(word) < self._min_word_len:
            return None
        candidates = self._candidates(word)
        if not candidates:
            return None
        valid = [c for c in candidates if _is_close_d1(word, c)]
        if not valid:
            return None
        return max(valid, key=lambda c: self._vocab.get(c, 0))

    def correct_query(self, query: str) -> tuple[str, dict[str, str]]:
        """Корректирует все out-of-vocab токены ≥ min_word_len в запросе.

        Возвращает `(corrected_query, {original_lower: corrected})`. Сохраняет
        пунктуацию, пробелы, цифры; case первой буквы наследуется от оригинала.
        Если коррекций нет — `corrected_query == query` и dict пустой.
        """
        corrections: dict[str, str] = {}

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            token_lower = token.lower()
            corrected = self.correct_word(token_lower)
            if corrected is None or corrected == token_lower:
                return token
            corrections[token_lower] = corrected
            if token[:1].isupper():
                return corrected[:1].upper() + corrected[1:]
            return corrected

        corrected_query = _WORD_RE.sub(repl, query)
        return corrected_query, corrections


# === Module-level singleton (used by FastAPI lifespan in main.py) ===

_corrector: Optional[SpellCorrector] = None


def init_from_vocab(vocab_freq: dict[str, int]) -> SpellCorrector:
    """Строит singleton SpellCorrector. Вызывается в lifespan event после BM25."""
    global _corrector
    _corrector = SpellCorrector(vocab_freq)
    return _corrector


def get_corrector() -> Optional[SpellCorrector]:
    return _corrector
