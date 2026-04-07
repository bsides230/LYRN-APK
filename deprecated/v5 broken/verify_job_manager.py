from playwright.sync_api import sync_playwright
import os

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Load the file
        cwd = os.getcwd()
        file_path = f"file://{cwd}/LYRN_v5/modules/Job Manager.html"
        print(f"Loading {file_path}")
        page.goto(file_path)

        # Switch to History tab
        page.click("button[onclick=\"switchTab('history')\"]")

        # Inject data
        page.evaluate("""
            DATA.history = [
                {
                    "job_name": "Test Job 1",
                    "status": "success",
                    "timestamp": new Date().toISOString(),
                    "details": [],
                    "filepath": "jobs/test_job.txt"
                },
                {
                    "job_name": "Test Job 2",
                    "status": "failed",
                    "timestamp": new Date().toISOString(),
                    "details": []
                }
            ];
            renderHistory();
        """)

        # Check for Clear History button
        delete_btn = page.query_selector(".btn-delete[title='Clear History']")
        if delete_btn:
            print("Clear History button found.")
        else:
            print("Clear History button NOT found.")

        # Check for View Output button
        view_btn = page.get_by_text("VIEW OUTPUT")
        if view_btn.is_visible():
             print("View Output button found.")
        else:
             print("View Output button NOT found.")

        # Take screenshot
        page.screenshot(path="/home/jules/verification/job_manager.png")
        print("Screenshot saved to /home/jules/verification/job_manager.png")

        browser.close()

if __name__ == "__main__":
    run()
