"""Wrapper around Together AI's Completion API."""

import logging
import warnings
from typing import Any, Dict, List, Optional

import requests
from aiohttp import ClientSession
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.llms import LLM
from langchain_core.pydantic_v1 import SecretStr, root_validator
from langchain_core.utils import convert_to_secret_str, get_from_dict_or_env

logger = logging.getLogger(__name__)


class Together(LLM):
    """LLM models from `Together`.

    To use, you'll need an API key which you can find here:
    https://api.together.ai/settings/api-keys. This can be passed in as init param
    ``together_api_key`` or set as environment variable ``TOGETHER_API_KEY``.

    Together AI API reference: https://docs.together.ai/reference/completions

    Example:
        .. code-block:: python

            from langchain_together import Together

            model = Together(model_name="mistralai/Mixtral-8x7B-Instruct-v0.1")
    """

    base_url: str = "https://api.together.ai/v1/completions"
    """Base completions API URL."""
    together_api_key: SecretStr
    """Together AI API key. Get it here: https://api.together.ai/settings/api-keys"""
    model: str
    """Model name. Available models listed here:
        Base Models: https://docs.together.ai/docs/inference-models#language-models
        Chat Models: https://docs.together.ai/docs/inference-models#chat-models
    """
    temperature: Optional[float] = None
    """Model temperature."""
    top_p: Optional[float] = None
    """Used to dynamically adjust the number of choices for each predicted token based
        on the cumulative probabilities. A value of 1 will always yield the same
        output. A temperature less than 1 favors more correctness and is appropriate
        for question answering or summarization. A value greater than 1 introduces more
        randomness in the output.
    """
    top_k: Optional[int] = None
    """Used to limit the number of choices for the next predicted word or token. It
        specifies the maximum number of tokens to consider at each step, based on their
        probability of occurrence. This technique helps to speed up the generation
        process and can improve the quality of the generated text by focusing on the
        most likely options.
    """
    max_tokens: Optional[int] = None
    """The maximum number of tokens to generate."""
    repetition_penalty: Optional[float] = None
    """A number that controls the diversity of generated text by reducing the
        likelihood of repeated sequences. Higher values decrease repetition.
    """
    logprobs: Optional[int] = None
    """An integer that specifies how many top token log probabilities are included in
        the response for each token generation step.
    """

    class Config:
        """Configuration for this pydantic object."""

        extra = "forbid"

    @root_validator(pre=True)
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key exists in environment."""
        values["together_api_key"] = convert_to_secret_str(
            get_from_dict_or_env(values, "together_api_key", "TOGETHER_API_KEY")
        )
        return values

    @root_validator()
    def validate_max_tokens(cls, values: Dict) -> Dict:
        """The v1 completions endpoint, has max_tokens as required parameter.

        Set a default value and warn if the parameter is missing.
        """
        if values.get("max_tokens") is None:
            warnings.warn(
                "The completions endpoint, has 'max_tokens' as required argument. "
                "The default value is being set to 200 "
                "Consider setting this value, when initializing LLM"
            )
            values["max_tokens"] = 200  # Default Value
        return values

    @property
    def _llm_type(self) -> str:
        """Return type of model."""
        return "together"

    def _format_output(self, output: dict) -> str:
        return output["choices"][0]["text"]

    @property
    def default_params(self) -> Dict[str, Any]:
        """Return the default parameters for the Together model.

        Returns:
            A dictionary containing the default parameters.
        """
        return {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "repetition_penalty": self.repetition_penalty,
        }

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Call out to Together's text generation endpoint.

        Args:
            prompt: The prompt to pass into the model.
            stop: Optional list of stop words to use when generating.
            run_manager: The CallbackManager for LLM run, it's not used at the moment.
            kwargs: Additional parameters to pass to the model.

        Returns:
            The string generated by the model..
        """
        headers = {
            "Authorization": f"Bearer {self.together_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        stop_to_use = stop[0] if stop and len(stop) == 1 else stop
        payload: Dict[str, Any] = {
            **self.default_params,
            "prompt": prompt,
            "stop": stop_to_use,
            **kwargs,
        }

        # filter None values to not pass them to the http payload
        payload = {k: v for k, v in payload.items() if v is not None}
        response = requests.post(url=self.base_url, json=payload, headers=headers)

        if response.status_code >= 500:
            raise Exception(f"Together Server: Error {response.status_code}")
        elif response.status_code >= 400:
            raise ValueError(f"Together received an invalid payload: {response.text}")
        elif response.status_code != 200:
            raise Exception(
                f"Together returned an unexpected response with status "
                f"{response.status_code}: {response.text}"
            )

        data = response.json()

        output = self._format_output(data)

        return output

    async def _acall(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Call Together model to get predictions based on the prompt.

        Args:
            prompt: The prompt to pass into the model.
            stop: Optional list of stop words to use when generating.
            run_manager: The CallbackManager for LLM run, it's not used at the moment.
            kwargs: Additional parameters to pass to the model.

        Returns:
            The string generated by the model.
        """
        headers = {
            "Authorization": f"Bearer {self.together_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        stop_to_use = stop[0] if stop and len(stop) == 1 else stop
        payload: Dict[str, Any] = {
            **self.default_params,
            "prompt": prompt,
            "stop": stop_to_use,
            **kwargs,
        }

        # filter None values to not pass them to the http payload
        payload = {k: v for k, v in payload.items() if v is not None}
        async with ClientSession() as session:
            async with session.post(
                self.base_url, json=payload, headers=headers
            ) as response:
                if response.status >= 500:
                    raise Exception(f"Together Server: Error {response.status}")
                elif response.status >= 400:
                    raise ValueError(
                        f"Together received an invalid payload: {response.text}"
                    )
                elif response.status != 200:
                    raise Exception(
                        f"Together returned an unexpected response with status "
                        f"{response.status}: {response.text}"
                    )

                response_json = await response.json()

                output = self._format_output(response_json)
                return output
