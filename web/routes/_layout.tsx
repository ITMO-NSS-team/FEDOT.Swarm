import { Header } from "@/components/Header.tsx";
import { define } from "@/utils.ts";

export default define.layout(({ Component, url }) => (
  <div class="page-shell">
    <Header pathname={url.pathname} />
    <Component />
  </div>
));
