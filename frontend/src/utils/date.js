/**
 * Форматирует ISO-дату (YYYY-MM-DD или полный ISO) в человекочитаемый
 * относительный формат: «вчера», «3 дня назад», «2 месяца назад», «1 год назад».
 * Возвращает null если вход невалидный — пилюля скроет блок.
 */
export function formatLastmod(input, now = new Date()) {
  if (!input) return null;
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return null;

  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffDays < 0) {
    // дата в будущем — отдадим как «обновлено сегодня»
    return "обновлено сегодня";
  }
  if (diffDays === 0) return "обновлено сегодня";
  if (diffDays === 1) return "обновлено вчера";
  if (diffDays < 7) return `обновлено ${diffDays} ${pluralRu(diffDays, ["день", "дня", "дней"])} назад`;
  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7);
    return `обновлено ${weeks} ${pluralRu(weeks, ["неделя", "недели", "недель"])} назад`;
  }
  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30);
    return `обновлено ${months} ${pluralRu(months, ["месяц", "месяца", "месяцев"])} назад`;
  }
  const years = Math.floor(diffDays / 365);
  return `обновлено ${years} ${pluralRu(years, ["год", "года", "лет"])} назад`;
}

function pluralRu(n, forms) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
  return forms[2];
}
