from dotenv import load_dotenv

# Load local overrides first, then fallback to .env
load_dotenv(".env.local")
load_dotenv(".env") 