"""
Browser Automation Base - Shared utilities for browser-based skills.

Provides common functionality for skills that need to automate websites:
- Session management (save/load cookies)
- Browser lifecycle management
- Anti-detection measures
- Common page interactions

Used by: Swiggy, BookMyShow, MakeMyTrip, Zomato, etc.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserAutomationBase:
    """
    Base class for browser automation skills.

    Handles:
    - Browser lifecycle (start, stop, reuse)
    - Session persistence (cookies, local storage)
    - Anti-detection measures
    - Common interactions (click, fill, wait)
    """

    # Override in subclass
    SERVICE_NAME = "base"
    SERVICE_URL = "https://example.com"
    LOGIN_URL = "https://example.com/login"
    LOGIN_CHECK_URL = "https://example.com/account"

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.session_dir = self.data_dir / f"{self.SERVICE_NAME}_session"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.session_file = self.session_dir / "cookies.json"
        self.state_file = self.session_dir / "state.json"

        # Browser instances
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        # State
        self._logged_in = False
        self._state: Dict[str, Any] = {}

        self._load_state()

    def _load_state(self):
        """Load saved state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self._state = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load {self.SERVICE_NAME} state: {e}")
                self._state = {}

    def _save_state(self):
        """Save state to disk."""
        try:
            self._state['updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save {self.SERVICE_NAME} state: {e}")

    async def _ensure_browser(self, headless: bool = True) -> Page:
        """
        Ensure browser is running and return page.

        Reuses existing browser if available.
        Loads saved session if exists.
        """
        if self._page and not self._page.is_closed():
            return self._page

        # Start playwright if needed
        if not self._playwright:
            self._playwright = await async_playwright().start()

        # Launch browser
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )

        # Context options
        context_options = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": self._get_user_agent(),
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
        }

        # Load saved session if available
        if self.session_file.exists():
            try:
                context_options["storage_state"] = str(self.session_file)
                logger.debug(f"Loading saved session for {self.SERVICE_NAME}")
            except Exception as e:
                logger.warning(f"Failed to load session: {e}")

        self._context = await self._browser.new_context(**context_options)
        self._page = await self._context.new_page()

        # Set extra headers
        await self._page.set_extra_http_headers({
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        })

        # Add stealth scripts
        await self._add_stealth_scripts()

        return self._page

    def _get_user_agent(self) -> str:
        """Get a realistic user agent."""
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    async def _add_stealth_scripts(self):
        """Add scripts to avoid bot detection."""
        if not self._page:
            return

        # Hide webdriver
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Mock plugins
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)

        # Mock languages
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-IN', 'en', 'hi']
            });
        """)

    async def save_session(self):
        """Save browser session for future use."""
        if self._context:
            try:
                await self._context.storage_state(path=str(self.session_file))
                logger.info(f"{self.SERVICE_NAME} session saved")
            except Exception as e:
                logger.warning(f"Failed to save session: {e}")

    async def close_browser(self, save: bool = True):
        """Close browser and optionally save session."""
        if save:
            await self.save_session()

        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def check_logged_in(self) -> bool:
        """
        Check if user is logged in.

        Override in subclass with service-specific logic.
        """
        try:
            page = await self._ensure_browser()
            await page.goto(self.LOGIN_CHECK_URL, wait_until="networkidle", timeout=15000)

            # If redirected to login page, not logged in
            if "login" in page.url.lower() or "signin" in page.url.lower():
                self._logged_in = False
                return False

            self._logged_in = True
            return True

        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
            return False

    async def login_interactive(self) -> Dict[str, Any]:
        """
        Open browser for interactive login.

        Returns instructions for user.
        """
        try:
            page = await self._ensure_browser(headless=False)
            await page.goto(self.LOGIN_URL, wait_until="networkidle")

            return {
                "status": "waiting",
                "message": f"🔐 {self.SERVICE_NAME.title()} Login Required\n\n"
                          f"A browser window has opened. Please:\n"
                          f"1. Complete the login process\n"
                          f"2. Once logged in, come back here\n\n"
                          f"Your session will be saved for future use.",
                "action_required": "manual_login"
            }

        except Exception as e:
            return {"status": "error", "message": f"Failed to open browser: {e}"}

    # ============ Common Page Interactions ============

    async def safe_click(self, selector: str, timeout: int = 5000) -> bool:
        """Safely click an element, return success status."""
        if not self._page:
            return False

        try:
            await self._page.click(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.debug(f"Click failed for {selector}: {e}")
            return False

    async def safe_fill(self, selector: str, value: str, timeout: int = 5000) -> bool:
        """Safely fill an input, return success status."""
        if not self._page:
            return False

        try:
            await self._page.fill(selector, value, timeout=timeout)
            return True
        except Exception as e:
            logger.debug(f"Fill failed for {selector}: {e}")
            return False

    async def safe_get_text(self, selector: str, timeout: int = 5000) -> Optional[str]:
        """Safely get text from element."""
        if not self._page:
            return None

        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if element:
                return await element.inner_text()
        except Exception as e:
            logger.debug(f"Get text failed for {selector}: {e}")

        return None

    async def wait_for_navigation(self, timeout: int = 30000):
        """Wait for page navigation."""
        if self._page:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)

    async def scroll_to_bottom(self, delay: float = 0.5):
        """Scroll to bottom of page to load lazy content."""
        if not self._page:
            return

        await self._page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        await asyncio.sleep(delay)

    async def extract_list(self, container_selector: str,
                           item_selector: str,
                           fields: Dict[str, str],
                           limit: int = 20) -> List[Dict[str, str]]:
        """
        Extract a list of items from page.

        Args:
            container_selector: Selector for container element
            item_selector: Selector for individual items within container
            fields: Dict of field_name -> selector within each item
            limit: Maximum items to extract

        Returns:
            List of dicts with extracted fields
        """
        if not self._page:
            return []

        results = []

        try:
            items = await self._page.query_selector_all(f"{container_selector} {item_selector}")

            for item in items[:limit]:
                data = {}
                for field_name, field_selector in fields.items():
                    try:
                        el = await item.query_selector(field_selector)
                        if el:
                            data[field_name] = (await el.inner_text()).strip()
                    except:
                        pass

                if data:
                    results.append(data)

        except Exception as e:
            logger.debug(f"Extract list failed: {e}")

        return results

    async def take_screenshot(self, name: str = "screenshot") -> Optional[str]:
        """Take a screenshot for debugging."""
        if not self._page:
            return None

        try:
            path = self.session_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await self._page.screenshot(path=str(path))
            return str(path)
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return None


# ============ Standalone Helper Functions ============

# Shared browser context for skills that don't use the class-based approach
_shared_playwright = None
_shared_browser = None
_shared_contexts: Dict[str, BrowserContext] = {}


async def get_browser_context(
    session_dir: str = "./data/browser_session",
    headless: bool = True,
    reuse: bool = True
) -> BrowserContext:
    """
    Get a browser context for browser automation.

    This is a standalone helper for skills that prefer function-based approach
    over the class-based BrowserAutomationBase.

    Args:
        session_dir: Directory to store session data (cookies)
        headless: Run browser in headless mode
        reuse: Reuse existing context if available

    Returns:
        BrowserContext ready for use
    """
    global _shared_playwright, _shared_browser, _shared_contexts

    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError("Playwright not available. Install with: pip install playwright && playwright install chromium")

    # Check for existing context
    if reuse and session_dir in _shared_contexts:
        ctx = _shared_contexts[session_dir]
        try:
            # Check if context is still valid
            pages = ctx.pages
            return ctx
        except:
            # Context is closed, remove it
            del _shared_contexts[session_dir]

    # Start playwright if needed
    if not _shared_playwright:
        _shared_playwright = await async_playwright().start()

    # Launch browser if needed
    if not _shared_browser or not _shared_browser.is_connected():
        _shared_browser = await _shared_playwright.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
            ]
        )

    # Create context with anti-detection
    context = await _shared_browser.new_context(
        viewport={'width': 1366, 'height': 768},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-IN',
        timezone_id='Asia/Kolkata',
    )

    # Load cookies if available
    session_path = Path(session_dir)
    session_path.mkdir(parents=True, exist_ok=True)
    cookies_file = session_path / "cookies.json"

    if cookies_file.exists():
        try:
            with open(cookies_file, 'r') as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            logger.debug(f"Loaded {len(cookies)} cookies from {cookies_file}")
        except Exception as e:
            logger.warning(f"Failed to load cookies: {e}")

    # Store for reuse
    _shared_contexts[session_dir] = context

    return context


async def save_browser_session(context: BrowserContext, session_dir: str):
    """
    Save browser session (cookies) to disk.

    Args:
        context: Browser context to save
        session_dir: Directory to save session data
    """
    try:
        cookies = await context.cookies()
        session_path = Path(session_dir)
        session_path.mkdir(parents=True, exist_ok=True)
        cookies_file = session_path / "cookies.json"

        with open(cookies_file, 'w') as f:
            json.dump(cookies, f)

        logger.debug(f"Saved {len(cookies)} cookies to {cookies_file}")
    except Exception as e:
        logger.warning(f"Failed to save session: {e}")


async def close_all_browsers():
    """Close all shared browser instances."""
    global _shared_playwright, _shared_browser, _shared_contexts

    for ctx in _shared_contexts.values():
        try:
            await ctx.close()
        except:
            pass
    _shared_contexts.clear()

    if _shared_browser:
        try:
            await _shared_browser.close()
        except:
            pass
        _shared_browser = None

    if _shared_playwright:
        try:
            await _shared_playwright.stop()
        except:
            pass
        _shared_playwright = None


# Alias for backward compatibility
BrowserBase = BrowserAutomationBase
