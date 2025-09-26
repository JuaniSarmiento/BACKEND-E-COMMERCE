from pydantic import BaseModel

class CardToken(BaseModel):
    token: str
