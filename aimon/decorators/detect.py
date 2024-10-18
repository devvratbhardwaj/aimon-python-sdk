from functools import wraps
import os

from aimon import Client


class Application:
    def __init__(self, name, stage="evaluation", type="text", metadata={}):
        self.name = name
        self.stage = stage
        self.type = type
        self.metadata = metadata


class Model:
    def __init__(self, name, model_type, metadata={}):
        self.name = name
        self.model_type = model_type
        self.metadata = metadata

class DetectResult:
    def __init__(self, status, detect_response, publish=None):
        self.status = status
        self.detect_response = detect_response
        self.publish_response = publish if publish is not None else []

    def __str__(self):
        return f"DetectResult(status={self.status}, detect_response={self.detect_response}, publish_response={self.publish_response})"

    def __repr__(self):
        return str(self)

class Detect:
    """
    A decorator class for detecting various qualities in LLM-generated text using AIMon's detection services.

    This decorator wraps a function that generates text using an LLM and sends the generated text
    along with context to AIMon for analysis. It can be used in both synchronous and asynchronous modes,
    and optionally publishes results to the AIMon UI.

    Parameters:
    -----------
    values_returned : list
        A list of values in the order returned by the decorated function.
        Acceptable values are 'generated_text', 'context', 'user_query', 'instructions'.
    api_key : str, optional
        The API key to use for the AIMon client. If not provided, it will attempt to use the AIMON_API_KEY environment variable.
    config : dict, optional
        A dictionary of configuration options for the detector. Defaults to {'hallucination': {'detector_name': 'default'}}.
    async_mode : bool, optional
        If True, the detect() function will return immediately with a DetectResult object. Default is False.
    publish : bool, optional
        If True, the payload will be published to AIMon and can be viewed on the AIMon UI. Default is False.
    application_name : str, optional
        The name of the application to use when publish is True.
    model_name : str, optional
        The name of the model to use when publish is True.

    Example:
    --------
    >>> from aimon.decorators import Detect
    >>> import os
    >>> 
    >>> # Configure the detector
    >>> detect = Detect(
    ...     values_returned=['context', 'generated_text', 'user_query'],
    ...     api_key=os.getenv('AIMON_API_KEY'),
    ...     config={
    ...         'hallucination': {'detector_name': 'default'},
    ...         'toxicity': {'detector_name': 'default'}
    ...     },
    ...     publish=True,
    ...     application_name='my_summarization_app',
    ...     model_name='gpt-3.5-turbo'
    ... )
    >>> 
    >>> # Define a simple lambda function to simulate an LLM
    >>> your_llm_function = lambda context, query: f"Summary of '{context}' based on query: {query}"
    >>> 
    >>> # Use the decorator on your LLM function
    >>> @detect
    ... def generate_summary(context, query):
    ...     summary = your_llm_function(context, query)
    ...     return context, summary, query
    >>> 
    >>> # Use the decorated function
    >>> context = "The quick brown fox jumps over the lazy dog."
    >>> query = "Summarize the given text."
    >>> context, summary, query, aimon_result = generate_summary(context, query)
    >>> 
    >>> # Print the generated summary
    >>> print(f"Generated summary: {summary}")
    >>> 
    >>> # Check the AIMon detection results
    >>> print(f"Hallucination score: {aimon_result.detect_response.hallucination['score']}")
    >>> print(f"Toxicity score: {aimon_result.detect_response.toxicity['score']}")
    """
    DEFAULT_CONFIG = {'hallucination': {'detector_name': 'default'}}

    def __init__(self, values_returned, api_key=None, config=None, async_mode=False, publish=False, application_name=None, model_name=None):
        """
        :param values_returned: A list of values in the order returned by the decorated function
                                Acceptable values are 'generated_text', 'context', 'user_query', 'instructions'
        :param api_key: The API key to use for the AIMon client
        :param config: A dictionary of configuration options for the detector
        :param async_mode: Boolean, if True, the detect() function will return immediately with a DetectResult object. Default is False.
                           The payload will also be published to AIMon and can be viewed on the AIMon UI.
        :param publish: Boolean, if True, the payload will be published to AIMon and can be viewed on the AIMon UI. Default is False.
        :param application_name: The name of the application to use when publish is True
        :param model_name: The name of the model to use when publish is True
        """
        api_key = os.getenv('AIMON_API_KEY') if not api_key else api_key
        if api_key is None:
            raise ValueError("API key is None")
        self.client = Client(auth_header="Bearer {}".format(api_key))
        self.config = config if config else self.DEFAULT_CONFIG
        self.values_returned = values_returned
        if self.values_returned is None or len(self.values_returned) == 0:
            raise ValueError("values_returned by the decorated function must be specified")
        if "context" not in self.values_returned:
            raise ValueError("values_returned must contain 'context'")
        self.async_mode = async_mode
        self.publish = publish
        if self.async_mode:
            self.publish = True
        if self.publish:
            if application_name is None:
                raise ValueError("Application name must be provided if publish is True")
            if model_name is None:
                raise ValueError("Model name must be provided if publish is True")
            self.application = Application(application_name, stage="production")
            self.model = Model(model_name, "text")
            self._initialize_application_model()
        
    def _initialize_application_model(self):
        # Create or retrieve the model
        self._am_model = self.client.models.create(
            name=self.model.name,
            type=self.model.model_type,
            description="This model is named {} and is of type {}".format(self.model.name, self.model.model_type),
            metadata=self.model.metadata
        )

        # Create or retrieve the application
        self._am_app = self.client.applications.create(
            name=self.application.name,
            model_name=self._am_model.name,
            stage=self.application.stage,
            type=self.application.type,
            metadata=self.application.metadata
        )

    def _call_analyze(self, result_dict):
        if "generated_text" not in result_dict:
            raise ValueError("Result of the wrapped function must contain 'generated_text'")
        if "context" not in result_dict:
            raise ValueError("Result of the wrapped function must contain 'context'")
        _context = result_dict['context'] if isinstance(result_dict['context'], list) else [result_dict['context']]
        aimon_payload = {
            "application_id": self._am_app.id,
            "version": self._am_app.version,
            "output": result_dict['generated_text'],
            "context_docs": _context,
            "user_query": result_dict["user_query"] if 'user_query' in result_dict else "No User Query Specified",
            "prompt": result_dict['prompt'] if 'prompt' in result_dict else "No Prompt Specified",
        }
        if 'instructions' in result_dict:
            aimon_payload['instructions'] = result_dict['instructions']
        if 'actual_request_timestamp' in result_dict:
            aimon_payload["actual_request_timestamp"] = result_dict['actual_request_timestamp']

        aimon_payload['config'] = self.config
        analyze_response = self.client.analyze.create(body=[aimon_payload])
        return analyze_response
    

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            # Handle the case where the result is a single value
            if not isinstance(result, tuple):
                result = (result,)

            # Create a dictionary mapping output names to results
            result_dict = {name: value for name, value in zip(self.values_returned, result)}

            aimon_payload = {}
            if 'generated_text' in result_dict:
                aimon_payload['generated_text'] = result_dict['generated_text']
            else:
                raise ValueError("Result of the wrapped function must contain 'generated_text'")
            if 'context' in result_dict:
                aimon_payload['context'] = result_dict['context']
            else:
                raise ValueError("Result of the wrapped function must contain 'context'")
            if 'user_query' in result_dict:
                aimon_payload['user_query'] = result_dict['user_query']
            if 'instructions' in result_dict:
                aimon_payload['instructions'] = result_dict['instructions']
            aimon_payload['config'] = self.config

            data_to_send = [aimon_payload]

            if self.async_mode:
                analyze_res = self._call_analyze(result_dict)
                return result + (DetectResult(analyze_res.status, analyze_res),)
            else:
                detect_response = self.client.inference.detect(body=data_to_send)[0]
                if self.publish:
                    analyze_res = self._call_analyze(result_dict)
                    return result + (DetectResult(max(200 if detect_response is not None else 500, analyze_res.status), detect_response, analyze_res),)
                return result + (DetectResult(200 if detect_response is not None else 500, detect_response),)

        return wrapper
