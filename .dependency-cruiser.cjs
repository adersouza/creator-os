/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "pipeline-contracts-remain-foundational",
      severity: "error",
      comment:
        "Shared contracts must stay below apps and runtime adapters; app/runtime imports here create circular ownership.",
      from: { path: "^packages/pipeline_contracts/" },
      to: { path: "^(apps|python_packages)/" },
    },
    {
      name: "tribe-research-not-operational-gate",
      severity: "error",
      comment:
        "TRIBE v2 is research/advisory only and must not be imported into readiness, scheduling, or publishing paths.",
      from: {
        path: "(readiness|schedule|scheduled|publish|publishing|qstash|daily-plan|inventory)",
      },
      to: {
        path: "(tribe|tribev2)",
      },
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
    },
    exclude: {
      path: [
        "node_modules",
        "storybook-static",
        "dist",
        "build",
        "coverage",
        "graphify-out",
        "\\.pytest_cache",
        "__pycache__",
      ].join("|"),
    },
    tsPreCompilationDeps: true,
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["import", "require", "node", "default"],
    },
  },
};
