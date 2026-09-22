import { Icon } from "@/components/Icon.tsx";

const links = [
  { href: "/", label: "Compose", icon: "compose" as const },
  { href: "/runs", label: "Runs", icon: "runs" as const },
];

export function Header({ pathname }: { pathname: string }) {
  const path = pathname.replace(/\/+$/, "") || "/";
  const active = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
  return (
    <>
      <a class="skip-link" href="#main-content">Skip to content</a>
      <header class="tool-rail">
        <nav class="tool-nav" aria-label="Primary navigation">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              aria-current={active(link.href) ? "page" : "false"}
            >
              <span class="nav-icon">
                <Icon name={link.icon} />
              </span>
              <span>{link.label}</span>
            </a>
          ))}
        </nav>
      </header>
    </>
  );
}
