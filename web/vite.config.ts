import { fresh } from "@fresh/plugin-vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [fresh()],
  // the end-to-end suite and its fixture are not the app: a change there must not reload it
  server: { watch: { ignored: ["**/e2e/**", "**/tests/fixtures/**"] } },
});
