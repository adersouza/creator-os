import { readFileSync } from "node:fs";
import { URL } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";

var schema = JSON.parse(readFileSync(
  new URL("../../pipeline_contracts/pipeline_contracts/schemas/contentforge_campaign_audit_response.v1.schema.json", import.meta.url),
  "utf8",
));
var validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);

export function assertCampaignFactoryAuditResponse(response) {
  if (validate(response)) return response;
  var detail = (validate.errors || []).map(function (error) {
    var path = error.instancePath || "$";
    if (error.keyword === "required") {
      return path + " missing " + error.params.missingProperty;
    }
    return path + " " + (error.message || "is invalid");
  }).join("; ");
  throw new Error("ContentForge Campaign Factory response contract violation: " + detail);
}
