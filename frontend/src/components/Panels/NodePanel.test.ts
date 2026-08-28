import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

describe("NodePanel", () => {
  it("binds the node search icon to Lucide", async () => {
    const source = await readFile(new URL("./NodePanel.vue", import.meta.url), "utf8");

    expect(source).toMatch(
      /import\s*\{[^}]*\bSearch\b[^}]*\}\s*from\s*"lucide-vue-next";/,
    );
  });
});
