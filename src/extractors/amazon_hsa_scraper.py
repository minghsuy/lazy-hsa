"""Amazon HSA-Eligible Order Scraper using Playwright + Vision LLM"""

import asyncio
import base64
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AmazonOrder:
    order_id: str
    order_date: datetime
    total: float
    items: list[str]
    is_hsa_eligible: bool
    screenshot_path: Optional[Path] = None
    invoice_path: Optional[Path] = None


class AmazonHSAScraper:
    """
    Scrape Amazon order history, detect HSA-eligible items via vision LLM,
    and download invoices only for eligible orders.
    """

    ORDER_HISTORY_URL = "https://www.amazon.com/gp/your-account/order-history"
    # Don't use direct signin URL - go to order history and let it redirect
    LOGIN_URL = "https://www.amazon.com/gp/your-account/order-history"

    def __init__(
        self,
        vision_extractor=None,
        downloads_dir: str = "tmp/amazon_invoices",
        headless: bool = False,
    ):
        """
        Args:
            vision_extractor: VisionExtractor instance for HSA detection
            downloads_dir: Where to save invoices
            headless: Run browser in headless mode (False = see the browser)
        """
        self.vision_extractor = vision_extractor
        self.downloads_dir = Path(downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        await self._start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_browser()

    async def _start_browser(self):
        """Start Playwright browser."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )
        self._page = await self._context.new_page()

    async def _close_browser(self):
        """Close browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def login(self, email: str, password: str) -> bool:
        """
        Log into Amazon. May require manual 2FA/CAPTCHA intervention.

        Args:
            email: Amazon account email
            password: Amazon account password

        Returns:
            True if login successful
        """
        page = self._page

        # Go to order history - will redirect to login if not authenticated
        await page.goto(self.LOGIN_URL)
        await page.wait_for_load_state("networkidle")

        # Check if already logged in
        if "order-history" in page.url and await page.query_selector(".order-card, .order"):
            logger.info("Already logged in")
            return True

        # Wait for login form to appear (Amazon redirects to signin)
        logger.info("Waiting for login page...")
        try:
            # Try email field first
            email_field = await page.wait_for_selector(
                "#ap_email, input[name='email']", timeout=10000
            )
            if email_field:
                await email_field.fill(email)
                # Click continue/next button
                continue_btn = await page.query_selector("#continue, input[type='submit']")
                if continue_btn:
                    await continue_btn.click()
                    await page.wait_for_load_state("networkidle")
        except Exception:
            logger.info("Email field not found, may need different flow")

        # Try password field
        try:
            password_field = await page.wait_for_selector(
                "#ap_password, input[name='password']", timeout=10000
            )
            if password_field:
                await password_field.fill(password)
                # Click sign in button
                signin_btn = await page.query_selector(
                    "#signInSubmit, input[type='submit'], button[type='submit']"
                )
                if signin_btn:
                    await signin_btn.click()
        except Exception:
            logger.info("Password field not found")

        # Wait for either success (redirect) or 2FA prompt
        # User may need to manually complete 2FA/CAPTCHA
        logger.info("Waiting for login... (complete 2FA/CAPTCHA if prompted)")
        logger.info("You have 60 seconds to complete any verification...")

        # Give user time to complete 2FA/CAPTCHA
        await page.wait_for_timeout(5000)

        # Check if we're logged in - either on order history or can see account nav
        for _ in range(12):  # Wait up to 60 seconds
            current_url = page.url
            if "order-history" in current_url:
                logger.info("Login successful - on order history page")
                return True

            # Check for account nav element
            account_nav = await page.query_selector("#nav-link-accountList")
            if account_nav:
                logger.info("Login successful")
                return True

            await page.wait_for_timeout(5000)

        logger.warning("Login may have failed or timed out")
        return False

    async def get_order_history(
        self, year: int = None, max_orders: int = 50
    ) -> list[dict]:
        """
        Navigate to order history and get list of orders.

        Args:
            year: Filter by year (default: current year)
            max_orders: Maximum orders to retrieve

        Returns:
            List of order dicts with basic info
        """
        year = year or datetime.now().year
        page = self._page

        # Go to order history for specific year
        url = f"{self.ORDER_HISTORY_URL}?timeFilter=year-{year}"
        await page.goto(url)
        await page.wait_for_load_state("networkidle")

        orders = []
        order_cards = await page.query_selector_all(".order-card, .order")

        for card in order_cards[:max_orders]:
            try:
                # Extract order ID
                order_id_elem = await card.query_selector("[data-order-id], .yohtmlc-order-id")
                order_id = None
                if order_id_elem:
                    order_id = await order_id_elem.get_attribute("data-order-id")
                    if not order_id:
                        text = await order_id_elem.inner_text()
                        match = re.search(r"\d{3}-\d{7}-\d{7}", text)
                        if match:
                            order_id = match.group()

                if order_id:
                    orders.append({"order_id": order_id})
            except Exception as e:
                logger.debug(f"Error parsing order card: {e}")

        logger.info(f"Found {len(orders)} orders for {year}")
        return orders

    async def check_order_hsa_eligible(self, order_id: str) -> tuple[bool, Path]:
        """
        Visit order detail page, take screenshot, use vision LLM to detect HSA badge.

        Args:
            order_id: Amazon order ID

        Returns:
            (is_hsa_eligible, screenshot_path)
        """
        page = self._page

        # Go to order details
        url = f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)  # Let dynamic content load

        # Take screenshot
        screenshot_path = self.downloads_dir / f"order_{order_id}_screenshot.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)

        # Use vision LLM to check for HSA eligibility
        is_eligible = await self._check_screenshot_for_hsa(screenshot_path)

        return is_eligible, screenshot_path

    async def _check_screenshot_for_hsa(self, screenshot_path: Path) -> bool:
        """Use vision LLM to detect HSA eligibility in screenshot."""
        if not self.vision_extractor:
            logger.warning("No vision extractor configured, skipping HSA check")
            return False

        # Read image and encode
        with open(screenshot_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Custom prompt for HSA detection
        prompt = """Look at this Amazon order screenshot carefully.

Is there ANY text that says "FSA or HSA eligible" or "FSA/HSA Eligible" or similar?

Respond with ONLY one word:
- YES if you see HSA/FSA eligibility mentioned anywhere
- NO if you don't see any HSA/FSA eligibility text"""

        try:
            response = self.vision_extractor._client.chat.completions.create(
                model=self.vision_extractor.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_data}"},
                            },
                        ],
                    }
                ],
                max_tokens=10,
                temperature=0,
            )
            answer = response.choices[0].message.content.strip().upper()
            return "YES" in answer
        except Exception as e:
            logger.error(f"Vision LLM check failed: {e}")
            return False

    async def download_invoice(self, order_id: str) -> Optional[Path]:
        """
        Download invoice PDF for an order.

        Args:
            order_id: Amazon order ID

        Returns:
            Path to downloaded PDF, or None if failed
        """
        page = self._page

        # Go to invoice page
        url = f"https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"
        await page.goto(url)
        await page.wait_for_load_state("networkidle")

        # Save as PDF
        invoice_path = self.downloads_dir / f"amazon_invoice_{order_id}.pdf"
        await page.pdf(path=str(invoice_path), format="Letter")

        logger.info(f"Downloaded invoice: {invoice_path}")
        return invoice_path

    async def scan_and_download_hsa_orders(
        self, email: str, password: str, year: int = None, max_orders: int = 50
    ) -> list[AmazonOrder]:
        """
        Full workflow: login, scan orders, detect HSA-eligible, download invoices.

        Args:
            email: Amazon email
            password: Amazon password
            year: Year to scan
            max_orders: Max orders to check

        Returns:
            List of AmazonOrder objects for HSA-eligible orders
        """
        hsa_orders = []

        # Login
        if not await self.login(email, password):
            logger.error("Login failed")
            return hsa_orders

        # Get order history
        orders = await self.get_order_history(year=year, max_orders=max_orders)

        # Check each order for HSA eligibility
        for order_info in orders:
            order_id = order_info["order_id"]
            logger.info(f"Checking order {order_id}...")

            is_eligible, screenshot_path = await self.check_order_hsa_eligible(order_id)

            if is_eligible:
                logger.info(f"  -> HSA ELIGIBLE! Downloading invoice...")
                invoice_path = await self.download_invoice(order_id)

                hsa_orders.append(
                    AmazonOrder(
                        order_id=order_id,
                        order_date=datetime.now(),  # Would extract from page
                        total=0.0,  # Would extract from page
                        items=[],  # Would extract from page
                        is_hsa_eligible=True,
                        screenshot_path=screenshot_path,
                        invoice_path=invoice_path,
                    )
                )
            else:
                logger.info(f"  -> Not HSA eligible, skipping")
                # Optionally delete screenshot
                screenshot_path.unlink(missing_ok=True)

        logger.info(f"Found {len(hsa_orders)} HSA-eligible orders")
        return hsa_orders


def get_keychain_password(service: str, account: str) -> str | None:
    """Get password from macOS Keychain."""
    import subprocess

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_amazon_credentials() -> tuple[str | None, str | None]:
    """Get Amazon credentials from environment or Keychain."""
    import os

    email = os.environ.get("AMAZON_EMAIL")
    password = os.environ.get("AMAZON_PASSWORD")

    # Try Keychain if env vars not set
    if not email or not password:
        # Try common Keychain service names
        for service in ["amazon-hsa", "amazon.com", "Amazon", "www.amazon.com"]:
            pw = get_keychain_password(service, "minghsun@gmail.com")
            if pw:
                email = "minghsun@gmail.com"
                password = pw
                break

    return email, password


async def main():
    """CLI for testing."""
    from src.processors.llm_extractor import get_extractor

    email, password = get_amazon_credentials()

    if not email or not password:
        print("Could not get Amazon credentials from environment or Keychain")
        print("Set AMAZON_EMAIL and AMAZON_PASSWORD, or add to macOS Keychain")
        return

    # Get vision extractor
    extractor = get_extractor(
        api_base="http://100.117.74.20:11434/v1",
        model="ministral-3:14b",
    )

    async with AmazonHSAScraper(vision_extractor=extractor, headless=False) as scraper:
        orders = await scraper.scan_and_download_hsa_orders(
            email=email, password=password, year=2026, max_orders=10
        )

        for order in orders:
            print(f"HSA Order: {order.order_id}")
            if order.invoice_path:
                print(f"  Invoice: {order.invoice_path}")


if __name__ == "__main__":
    asyncio.run(main())
