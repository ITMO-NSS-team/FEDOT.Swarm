/** A few icons, drawn rather than imported. The reference app carried a sheet of twenty for
 * screens this one does not have; the last four mark the explorer tabs of a finished run. */
const paths = {
  compose:
    "M12 20h9 M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z M14.5 5.5l3 3",
  swarm:
    "M12 4v5M12 15v5M6.5 7.5l3 3M14.5 13.5l3 3M4 12h5M15 12h5M6.5 16.5l3-3M14.5 10.5l3-3",
  runs: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3.5 2",
  paper: "M6 3h9l5 5v13H6z M15 3v5h5 M9 13h6 M9 17h6",
  voices:
    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M3 20v-1a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v1 M16 4.5a3.5 3.5 0 0 1 0 6.5 M18 14a5 5 0 0 1 3 4.6V20",
  rubric:
    "M4 6h3 M4 12h3 M4 18h3 M10 6h10 M10 12h10 M10 18h10 M4.5 5l1 1 1.5-2 M4.5 11l1 1 1.5-2",
  files:
    "M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  details: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 11v6 M12 8h.01",
} as const;

export type IconName = keyof typeof paths;

export function Icon(
  { name, size = 22 }: { name: IconName; size?: number },
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
