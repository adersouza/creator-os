/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "dashboard-ui-no-live-publish-runtime",
      severity: "error",
      comment:
        "Browser/UI code can render publishing state, but it must not import live publish, schedule, QStash, or Instagram mutation adapters directly.",
      from: {
        path: "^apps/dashboard/src/(components|contexts|hooks|lib|pages|routes|services|stores|utils)/",
        pathNot: "\\.(test|spec|stories)\\.(ts|tsx|js|jsx)$",
      },
      to: {
        path: "^apps/dashboard/api/_lib/(publishPost|publishPreflight|qstash|qstashSchedule|instagram/(publishing|orchestrate)|handlers/(auto-post-publish|posts/(schedule|campaignSchedule)))(\\.|/)",
      },
    },
    {
      name: "pipeline-contracts-remain-foundational",
      severity: "error",
      comment:
        "Shared contracts must stay below apps and runtime adapters; app/runtime imports here create circular ownership.",
      from: { path: "^packages/pipeline_contracts/" },
      to: { path: "^(apps|python_packages)/" },
    },
    {
      name: "contentforge-no-dashboard-runtime",
      severity: "error",
      comment:
        "ContentForge can exchange artifacts through contracts, but must not import dashboard runtime or API code.",
      from: { path: "^apps/contentforge/" },
      to: { path: "^apps/dashboard/" },
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
