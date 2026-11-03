"""Optional real-browser acceptance: pip install -r requirements-browser.txt."""
import json
import os
from pathlib import Path
import threading
import uuid
from playwright.sync_api import sync_playwright, expect
from src.web import WebApp, make_server

ROOT=Path(__file__).resolve().parents[1]


def main():
    storage=ROOT/"runs"/("browser-"+uuid.uuid4().hex)
    app=WebApp(storage)
    server=make_server(app,0)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    checks=[]
    errors=[]
    try:
        with sync_playwright() as p:
            edge=Path(os.environ.get("PROGRAMFILES(X86)","C:/Program Files (x86)"))/"Microsoft/Edge/Application/msedge.exe"
            browser=p.chromium.launch(headless=True,**({"executable_path":str(edge)} if edge.is_file() else {}))
            page=browser.new_page(viewport={"width":1440,"height":1000},device_scale_factor=1)
            page.on("pageerror",lambda error: errors.append(str(error)))
            page.goto("http://127.0.0.1:"+str(server.server_port))
            def start():
                with page.expect_response(lambda r: r.url.endswith("/api/runs") and r.request.method=="POST") as pending:
                    page.get_by_role("button",name="开始规划",exact=True).click()
                run_id=pending.value.json()["run_id"]
                expect(page.locator("#run-label")).to_contain_text(run_id[:8])
            start()
            expect(page.locator("#status")).to_have_text("已完成")
            assert page.locator("#cost").inner_text()=="8"
            assert page.locator(".flow-item").count()==6
            assert page.locator("#quote-chart .over-budget").count()==1
            assert page.locator("#quote-chart .bar").count()==1
            checks.append("Mock actual run: 12 -> 8; six tool steps and completed save")
            image_dir=ROOT/"docs"/"images"
            image_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(image_dir/"workbench-desktop.png"),full_page=True)
            page.get_by_role("tab",name="内容方案").click()
            assert "[lite]" in page.locator("#plan-content").inner_text()
            checks.append("Plan tab renders actual generated script")
            page.get_by_role("tab",name="Trace 明细").click()
            assert page.locator(".trace-event").count()==7
            with page.expect_download() as info:
                page.get_by_role("button",name="下载 JSONL").click()
            trace_path=storage/"download.jsonl"
            info.value.save_as(trace_path)
            assert len(trace_path.read_text(encoding="utf-8").splitlines())==7
            checks.append("Trace tab and actual JSONL download")
            start()
            expect(page.locator("#status")).to_have_text("已完成")
            assert page.locator("#charged").inner_text()=="0"
            checks.append("Duplicate request returns existing saved plan, zero charge")
            page.locator('[data-preset="resume"]').click()
            expect(page.locator("#failure")).to_have_value("generate_script")
            start()
            expect(page.locator("#status")).to_have_text("未完成")
            assert page.locator(".flow-item.failed").count()==1
            page.get_by_role("button",name="继续执行",exact=True).click()
            expect(page.locator("#status")).to_have_text("已完成")
            assert page.locator(".flow-item.failed").count()==1
            assert page.locator(".flow-item.succeeded").count()==4
            checks.append("Failure remains failed after resume; successful search reused")
            page.locator("#budget").fill("")
            start()
            expect(page.locator("#status")).to_have_text("待补充")
            assert "预算" in page.locator("#result-banner").inner_text()
            assert page.locator(".flow-item").count()==0
            checks.append("Missing input shown without any tool steps")
            page.locator("#budget").fill("5")
            page.locator("#max-steps").fill("12")
            start()
            expect(page.locator("#status")).to_have_text("未完成")
            assert "没有可行方案" in page.locator("#result-banner").inner_text()
            checks.append("No feasible plan displays computed gap")
            page.get_by_role("button",name="查看真实运行样例").click()
            page.locator('[data-id="18-real-observed-replan"]').click()
            expect(page.locator("#run-label")).to_contain_text("历史运行")
            assert "12" in page.locator("#quote-chart").inner_text()
            assert not page.locator("#resume-button").is_visible()
            checks.append("Archived real-model evidence is labelled and read-only")
            page.locator("#history-nav").click()
            expect(page.locator("#library .library-item")).to_have_count(5)
            page.get_by_role("button",name="关闭",exact=True).click()
            checks.append("Persisted history can be opened")
            page.set_viewport_size({"width":390,"height":844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(image_dir/"workbench-mobile.png"),full_page=True)
            checks.append("390px mobile layout has no horizontal overflow")
            page.locator("#topic").fill('<img src=x onerror="window.compromised=true">')
            page.locator("#budget").fill("10")
            page.locator("#failure").select_option("")
            start()
            expect(page.locator("#status")).to_have_text("已完成")
            assert page.evaluate("window.compromised === undefined")
            assert page.locator("#run-title img").count()==0
            checks.append("User topic is rendered as text, never executable HTML")
            assert not errors, errors
            browser.close()
        report={"browser":"Microsoft Edge / Playwright","checks":checks,"page_errors":errors,
                "passed":len(checks),"screenshots":["docs/images/workbench-desktop.png","docs/images/workbench-mobile.png"]}
        (ROOT/"examples"/"web-ui-results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        server.shutdown()
        server.server_close()
        app.close()
        worker.join()


if __name__=="__main__":
    main()
