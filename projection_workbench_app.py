from __future__ import annotations

import projection_workbench_ai as app

# projection_workbench_ai owns the backend behavior. This thin final assembly layer keeps
# UI-only QA wiring isolated so fixture controls cannot affect production research logic.
html = app.base.HTML
html = html.replace(
    "document.body.classList.add('draft-mode');\nconst draftBtn=$('draftGenerateBtn');",
    """const originalPayload=payload;
payload=function(){
  const p=originalPayload();
  if($('qaScenario'))p.qa_scenario=$('qaScenario').value;
  if($('qaDelay'))p.qa_delay=parseInt($('qaDelay').value||'0',10);
  return p;
};
document.body.classList.add('draft-mode');
const draftBtn=$('draftGenerateBtn');""",
    1,
)
app.base.HTML = html


if __name__ == "__main__":
    app.main()
