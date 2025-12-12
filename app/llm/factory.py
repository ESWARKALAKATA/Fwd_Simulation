from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import ChatOllama
# For OpenRouter, we can often use ChatOpenAI with a custom base_url
from app.config import settings
from app.llm.registry import registry

def get_llm(model_id: str) -> BaseChatModel:
    """
    Returns a LangChain Chat Model instance based on the model_id.
    """
    model_info = registry.get_model_info(model_id)
    if not model_info:
        # Fallback or raise error. For now, let's default to OpenAI if available, or raise.
        # If the user passed None or an invalid ID, we pick the first available.
        available = registry.list_models()
        if not available:
            raise ValueError("No LLM providers configured.")
        model_info = available[0]
        # print(f"Warning: Model {model_id} not found. Using default: {model_info['id']}")

    provider = model_info["provider"]
    
    if provider == "openai":
        # Extract model name from id "openai:gpt-4o-mini" -> "gpt-4o-mini"
        model_name = model_info["id"].split(":", 1)[1]
        return ChatOpenAI(
            model=model_name,
            api_key=settings.OPENAI_API_KEY,
            temperature=0
        )
    
    elif provider == "gemini":
        model_name = model_info["id"].split(":", 1)[1]
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0,
            convert_system_message_to_human=True
        )

    elif provider == "openrouter":
        # OpenRouter uses OpenAI-compatible API
        # User requested DeepSeek as default for OpenRouter
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            model="deepseek/deepseek-chat", 
            temperature=0
        )

    elif provider == "ollama":
        model_name = model_info["id"].split(":", 1)[1]
        return ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=model_name,
            temperature=0
        )

    raise ValueError(f"Unsupported provider: {provider}")
