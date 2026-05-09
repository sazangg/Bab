import { defineConfig } from "orval";

export default defineConfig({
  bab: {
    input: "http://localhost:8000/openapi.json",
    output: {
      target: "src/shared/api/generated/bab.ts",
      schemas: "src/shared/api/generated/schemas",
      client: "react-query",
      mode: "tags-split",
      override: {
        mutator: {
          path: "src/shared/api/orval-mutator.ts",
          name: "apiMutator",
        },
      },
    },
  },
});
