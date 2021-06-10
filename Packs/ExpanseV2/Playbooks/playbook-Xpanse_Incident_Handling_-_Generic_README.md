A generic playbook for handling Xpanse issues.
The logic behind this playbook is working with an internal exclusions list which will help the analyst to get a decision.
The phases of this playbook are:
  1) Check if assets (IP, Domain or Certificate) associated to the issue are excluded in the exclusions list.
  2) Optionally, enrich indicators and calculate the severity of the issue, using sub-playbooks.
  3) Optionally, allow the analyst to add associated assets (IP, Domain or Certificate) to the exclusions list.
  4) Tag associated assets.
  5) Update the status of the issue.

## Dependencies
This playbook uses the following sub-playbooks, integrations, and scripts.

### Sub-playbooks
* Expanse Load-Create List
* Extract and Enrich Expanse Indicators
* Calculate Severity - Standard

### Integrations
* ExpanseV2

### Scripts
* AddKeyToList
* SetAndHandleEmpty
* ExpanseRefreshIssueAssets
* Set

### Commands
* closeInvestigation
* expanse-assign-tags-to-asset
* expanse-get-certificate
* expanse-update-issue
* expanse-create-tag
* setIncident
* expanse-get-issue-comments

## Playbook Inputs
---

| **Name** | **Description** | **Default Value** | **Required** |
| --- | --- | --- | --- |
| ExclusionsList | The name of an internal XSOAR list which includes all whitelisted IP values or Domain values.  If no list currently exist, the playbook will create it for you with the givan name.<br/>The structure of this list should be:<br/><br/>\{<br/> "Addresses":\[<br/>    \{<br/>      "ip": "x.x.x.x",<br/>      "issueTypeID": "issueTypeIDHere",<br/>      "port": 123,<br/>      "protocol": "UDP"<br/>    \},<br/>    \{<br/>      "ip": "x.x.x.x",<br/>      "issueTypeID": "issueTypeIDHere",<br/>      "port": 456,<br/>      "protocol": "TCP"<br/>    \},<br/>    .<br/>    .<br/>    .<br/>  \],<br/>"Domains":\[<br/>   \{<br/>     "domain":"some.domain.com",<br/>     "issueTypeID": "issueTypeIDHere",<br/>     "port": 80,<br/>     "protocol": "TCP"<br/>   \}<br/>   .<br/>   .<br/>   .<br/> \] ,<br/>"Certificates":\[<br/>   \{<br/>     "sha256fingerprint":"value of sha256 fingerprin",<br/>     "issueTypeID": "issueTypeIDHere",<br/>     "subject": "certificate subject"<br/>   \}<br/>   .<br/>   .<br/>   .<br/> \]<br/>\}<br/><br/>For example:<br/><br/>\{<br/>   "Addresses":\[<br/>      \{<br/>         "ip":"10.0.0.1",<br/>         "issueTypeID":"MissingXFrameOptionsHeader",<br/>         "port":443,<br/>         "protocol": "TCP"<br/>      \},<br/>      \{<br/>         "ip":"10.0.0.2",<br/>         "issueTypeID":"WildcardCertificate",<br/>         "port":443,<br/>         "protocol": "TCP"<br/>      \}<br/>   \],<br/>   "Domains":\[<br/>	   \{<br/>	     "domain":"my.domain.com",<br/>	     "issueTypeID": "ApacheWebServer",<br/>	     "port": 443,<br/>	     "protocol": "TCP"<br/>	   \}	<br/>   \],<br/>   "Certificates":\[<br/>       \{<br/>         "sha256fingerprint":"f2ca1bb.....6fd2",<br/>     	 "issueTypeID": "ShortKeyCertificate",<br/>     	 "subject": "C=US,ST=WASHINGTON,L=.....E=John@test.com"<br/>   	\}<br/>   \]<br/>\}<br/><br/>In the above example, we will whitelist "MissingXFrameOptionsHeader" issue type ID on 10.0.0.1:443, "WildcardCertificate" issue type ID on 10.0.0.2:443, "ApacheWebServer" issue type ID on my.domain.com:443 And "ShortKeyCertificate" on a certificate with a specific sha256 fingerprint and subject.  | XpanseExclusionsList | Required |
| EnrichIndicators | Whether to extract and enrich indicators automatically using the "Entity Enrichment - Generic V3" playbook or not. | True | Optional |
| CalculateSeverity | Whether to calculate the severity of the incident automatically using the "Calculate Severity - Standard" playbook or not. | True | Optional |
| CommonTags | Common tags which your organization uses.<br/>Should be a comma separated list \(lower case letters\), for example:<br/>tag1, tag2, tag3 ... | test-env, production-env, excluded | Optional |
| OutgoingMirrorTag | If a value is provided for this field, the comment of the analyst will be tagged with it.<br/>In order to mirror it, please configure the same value under the integration's instance outgoing mirror configurations. | MirrorToXpanse | Optional |

## Playbook Outputs
---
There are no outputs for this playbook.

## Playbook Image
---
![Xpanse Incident Handling - Generic](Insert the link to your image here)