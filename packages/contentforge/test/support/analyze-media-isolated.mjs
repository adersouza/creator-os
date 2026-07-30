import { readFile } from "node:fs/promises";

import { analyzeTrustedMediaForIsolatedTest } from "../../lib/trusted-media-analysis.js";

var requestPath = process.argv[2];
if (requestPath) {
  var payload = JSON.parse(await readFile(requestPath, "utf8"));
  var result = await analyzeTrustedMediaForIsolatedTest(payload);
  process.stdout.write(JSON.stringify(result) + "\n");
}
