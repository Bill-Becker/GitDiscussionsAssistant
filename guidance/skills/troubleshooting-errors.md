---
name: Troubleshooting errors
keywords: error, errors, fail, fails, failed, failing, exception, crash, traceback, "stack trace", infeasible, bug
always: false
---
<!-- Starter skill: review and refine with REopt-specific details. -->

When the user reports an error or a failed run:

- First determine how they are running REopt: the REopt web tool, the REopt API, or the REopt.jl Julia package. Ask if it is not stated.
- Ask for the full error message, if they did not include it, and for their inputs in the form that fits how they ran REopt (only what they have not already provided):
  - **Web tool users:** any one of a link to their inputs page, a link to their results page, or the run_uuid. If the run errored and they cannot get either link, ask them to open their Saved Evaluations page, download the inputs.json file for that run, and attach it.
  - **API users:** their post.json file (the inputs they POSTed) and/or the run_uuid returned by their initial POST.
  - **REopt.jl users:** the package version and their inputs (scenario JSON or Dict), with sensitive data removed.
- For an infeasible or non-optimal solver status, suggest checking for conflicting constraints (e.g., required renewable fraction, outage requirements, or minimum sizes that cannot be met) before assuming a bug.
- Do not invent fixes; if the cause is unclear, suggest the team try to reproduce it with the user's inputs.
