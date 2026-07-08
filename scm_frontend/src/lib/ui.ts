// export function statusClass(status: string) {
//   if (status === "Red") return "pill pill-danger";
//   if (status === "Yellow") return "pill pill-warning";
//   if (status === "Green") return "pill pill-success";
//   return "pill";
// }
export function statusClass(status: string) {
  if (status === "Red") return "pill pill-danger";
  if (status === "Yellow") return "pill pill-warning";
  if (status === "Green") return "pill pill-success";
  return "pill";
}

export function stockColorClass(quantity: number, threshold: number): string {
  if (quantity <= threshold * 0.5) return "text-red";
  if (quantity <= threshold) return "text-yellow";
  return "text-green";
}