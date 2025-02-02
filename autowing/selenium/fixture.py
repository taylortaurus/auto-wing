from typing import Any, Dict
import json
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from autowing.core.llm.factory import LLMFactory
from autowing.core.ai_fixture_base import AiFixtureBase
from loguru import logger


class SeleniumAiFixture(AiFixtureBase):
    """
    A fixture class that combines Selenium with AI capabilities for web automation.
    Provides AI-driven interaction with web pages using various LLM providers.
    Maintains API compatibility with PlaywrightAiFixture.
    """

    def __init__(self, driver: WebDriver):
        """
        Initialize the AI-powered Selenium fixture.

        Args:
            driver (WebDriver): The Selenium WebDriver instance to automate
        """
        self.driver = driver
        self.llm_client = LLMFactory.create()
        self.wait = WebDriverWait(self.driver, 10)  # Default timeout of 10 seconds

    def _get_page_context(self) -> Dict[str, Any]:
        """
        Extract context information from the current page.
        Collects information about visible elements and page metadata.

        Returns:
            Dict[str, Any]: A dictionary containing page URL, title, and information about
                           visible interactive elements
        """
        # Get basic page info
        basic_info = {
            "url": self.driver.current_url,
            "title": self.driver.title
        }
        
        # Get key elements info using JavaScript
        elements_info = self.driver.execute_script("""
            const getVisibleElements = () => {
                const elements = [];
                const selectors = [
                    'input', 'button', 'a', '[role="button"]',
                    '[role="link"]', '[role="searchbox"]', 'textarea'
                ];
                
                for (const selector of selectors) {
                    document.querySelectorAll(selector).forEach(el => {
                        if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                            elements.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.getAttribute('type'),
                                placeholder: el.getAttribute('placeholder'),
                                value: el.value,
                                text: el.textContent?.trim(),
                                aria: el.getAttribute('aria-label'),
                                id: el.id,
                                name: el.getAttribute('name'),
                                class: el.className
                            });
                        }
                    });
                }
                return elements;
            };
            return getVisibleElements();
        """)
        
        return {
            **basic_info,
            "elements": elements_info
        }

    def ai_action(self, prompt: str) -> None:
        """
        Execute an AI-driven action on the page based on the given prompt.

        Args:
            prompt (str): Natural language description of the action to perform

        Raises:
            ValueError: If the AI response cannot be parsed or contains invalid instructions
            TimeoutException: If the element cannot be found or interacted with
        """
        logger.info(f"🪽 AI Action: {prompt}")
        context = self._get_page_context()
        
        action_prompt = f"""
Extract element locator and action from the request. Return ONLY a JSON object.

Page: {context['url']}
Title: {context['title']}
Request: {prompt}

Return format:
{{
    "selector": "CSS selector to locate the element",
    "action": "click/fill/press",
    "value": "text to input if needed",
    "key": "key to press if needed"
}}

No other text or explanation.
"""
        
        response = self.llm_client.complete(action_prompt)
        cleaned_response = self._clean_response(response)
        instruction = json.loads(cleaned_response)
        
        selector = instruction.get('selector')
        action = instruction.get('action')
        
        if not selector or not action:
            raise ValueError("Invalid instruction format")
            
        # Execute the action
        element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        
        if action == 'click':
            element.click()
        elif action == 'fill':
            element.clear()
            element.send_keys(instruction.get('value', ''))
            if instruction.get('key'):
                key_attr = getattr(Keys, instruction['key'].upper(), None)
                if key_attr:
                    element.send_keys(key_attr)
        elif action == 'press':
            key_attr = getattr(Keys, instruction.get('key', 'ENTER').upper())
            element.send_keys(key_attr)
        else:
            raise ValueError(f"Unsupported action: {action}")
            
    def ai_query(self, prompt: str) -> Any:
        """
        Query information from the page using AI analysis.

        Args:
            prompt (str): Natural language query about the page content.
                         Can include format hints like 'string[]' or 'number'.

        Returns:
            Any: The query results in the requested format

        Raises:
            ValueError: If the AI response cannot be parsed into the requested format
        """
        logger.info(f"🪽 AI Query: {prompt}")
        context = self._get_page_context()
        
        # Parse the requested data format
        format_hint = ""
        if prompt.startswith(('string[]', 'number[]', 'object[]')):
            format_hint = prompt.split(',')[0].strip()
            prompt = ','.join(prompt.split(',')[1:]).strip()

        # Provide different prompts based on the format
        if format_hint == 'string[]':
            query_prompt = f"""
Extract text content matching the query. Return ONLY a JSON array of strings.

Page: {context['url']}
Title: {context['title']}
Query: {prompt}

Return format example: ["result1", "result2"]
No other text or explanation.
"""
        elif format_hint == 'number[]':
            query_prompt = f"""
Extract numeric values matching the query. Return ONLY a JSON array of numbers.

Page: {context['url']}
Title: {context['title']}
Query: {prompt}

Return format example: [1, 2, 3]
No other text or explanation.
"""
        else:
            query_prompt = f"""
Extract information matching the query. Return ONLY in valid JSON format.

Page: {context['url']}
Title: {context['title']}
Query: {prompt}

Return format:
- For arrays: ["item1", "item2"]
- For objects: {{"key": "value"}}
- For single value: "text" or number

No other text or explanation.
"""

        response = self.llm_client.complete(query_prompt)
        cleaned_response = self._clean_response(response)
        try:
            result = json.loads(cleaned_response)
            query_info = self._validate_result_format(result, format_hint)
            logger.debug(f"📄 Query: {query_info}")
            return query_info
        except json.JSONDecodeError:
            # If it's a string array format, try extracting from text
            if format_hint == 'string[]':
                lines = [line.strip() for line in cleaned_response.split('\n') 
                        if line.strip() and not line.startswith(('-', '*', '#'))]
                
                query_terms = [term.lower() for term in prompt.split() 
                             if len(term) > 2 and term.lower() not in ['the', 'and', 'for']]
                
                results = []
                for line in lines:
                    if any(term in line.lower() for term in query_terms):
                        text = line.strip('`"\'- ,')
                        if ':' in text:
                            text = text.split(':', 1)[1].strip()
                        if text:
                            results.append(text)
                
                if results:
                    seen = set()
                    query_info = [x for x in results if not (x in seen or seen.add(x))]
                    logger.debug(f"📄 Query: {query_info}")
                    return query_info
            
            raise ValueError(f"Failed to parse response as JSON: {cleaned_response[:100]}...")
        
    def ai_assert(self, prompt: str) -> bool:
        """
        Verify a condition on the page using AI analysis.

        Args:
            prompt (str): Natural language description of the condition to verify

        Returns:
            bool: True if the condition is met, False otherwise

        Raises:
            ValueError: If the AI response cannot be parsed as a boolean value
        """
        logger.info(f"🪽 AI Assert: {prompt}")
        context = self._get_page_context()
        
        assert_prompt = f"""
You are a web automation assistant. Verify the following assertion and return ONLY a boolean value.

Page URL: {context['url']}
Page Title: {context['title']}

Assertion: {prompt}

IMPORTANT: Return ONLY the word 'true' or 'false' (lowercase). No other text, no explanation.
"""
        
        response = self.llm_client.complete(assert_prompt)
        cleaned_response = self._clean_response(response).lower()
        
        # Directly match true or false
        if cleaned_response == 'true':
            return True
        if cleaned_response == 'false':
            return False
        
        # If response contains other content, try extracting boolean
        if 'true' in cleaned_response.split():
            return True
        if 'false' in cleaned_response.split():
            return False
        
        raise ValueError("Response must be 'true' or 'false'")


def create_fixture():
    """
    Create a SeleniumAiFixture factory.
    """
    return SeleniumAiFixture
