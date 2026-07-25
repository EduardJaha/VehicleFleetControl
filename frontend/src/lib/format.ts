export function toApiDate(value: string): string {
  if (!value) return "";
  const htmlDate = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (htmlDate) {
    const [, year, month, day] = htmlDate;
    return `${day}-${month}-${year}`;
  }
  return value;
}

export function toInputDate(value: string): string {
  if (!value) return "";
  const apiDate = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
  if (apiDate) {
    const [, day, month, year] = apiDate;
    return `${year}-${month}-${day}`;
  }
  return value;
}

export function todayInputDate(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}
