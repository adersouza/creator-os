import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { URL } from "node:url";
import { assertCampaignFactoryAuditResponse } from "../lib/campaign-factory-contract.js";

var exampleUrl = new URL(
  "../../pipeline_contracts/pipeline_contracts/schemas/contentforge_campaign_audit_response.v1.example.json",
  import.meta.url,
);

test("Campaign Factory response contract accepts the canonical full response", async function () {
  var response = JSON.parse(await readFile(exampleUrl, "utf8"));
  assert.equal(assertCampaignFactoryAuditResponse(response), response);
});

test("Campaign Factory response contract rejects drift before returning it", async function () {
  var response = JSON.parse(await readFile(exampleUrl, "utf8"));
  delete response.readinessSummary.operatorLabels;
  assert.throws(
    function () { assertCampaignFactoryAuditResponse(response); },
    /response contract violation.*operatorLabels/,
  );
});
