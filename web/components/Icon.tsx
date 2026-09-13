/** Three icons, drawn rather than imported. The reference app carried a sheet of twenty for
 * screens this one does not have. */
const paths = {
  compose: "M4 5h16M4 12h10M4 19h7M17 15l4 4M21 15l-4 4",
  swarm:
    "M12 4v5M12 15v5M6.5 7.5l3 3M14.5 13.5l3 3M4 12h5M15 12h5M6.5 16.5l3-3M14.5 10.5l3-3",
  runs: "M4 6h16M4 12h16M4 18h9",
} as const;

export function Icon(
  { name, size = 22 }: { name: keyof typeof paths; size?: number },
) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
