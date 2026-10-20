from __future__ import annotations

import os

import projection_workbench_app as workbench

QA_MODE = bool(workbench.app.QA_MODE)

css = r'''
.module-nav{display:flex;align-items:center;justify-content:flex-start;margin:0 0 18px}
.module-back{display:inline-flex;align-items:center;gap:7px;color:#dbe4f3;text-decoration:none;font-weight:800;font-size:14px;padding:9px 12px;border:1px solid #304568;border-radius:12px;background:#0a1629}
.module-back:hover{border-color:#526b93;background:#0d1b31}
.module-back.disabled{opacity:.42;cursor:default;pointer-events:none}
'''

if QA_MODE:
    back = '<div class="module-nav"><span class="module-back disabled" aria-disabled="true">← Back to modules</span></div>'
else:
    back = '<div class="module-nav"><a class="module-back" href="http://127.0.0.1:8765/">← Back to modules</a></div>'

html = workbench.base.HTML
html = html.replace('</style></head>', css + '</style></head>', 1)
marker = '<body><main class="shell">'
if marker not in html:
    raise RuntimeError("Could not find Projection Workbench shell for module navigation.")
html = html.replace(marker, marker + back, 1)
workbench.base.HTML = html

# When the main Fantasy Decision Lab starts the workbench on demand, the browser is already
# navigating to it. Suppress the standalone launcher's second automatic browser tab.
if os.environ.get("FANTASY_PROJECTION_NO_BROWSER") == "1":
    workbench.webbrowser.open = lambda *_args, **_kwargs: True


def main():
    workbench.main()


if __name__ == "__main__":
    main()
