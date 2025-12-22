from pydantic import BaseModel, Field

class Settings(BaseModel):
    MS_BASE_URL: str = Field(default="https://api.moysklad.ru/api/remap/1.2")
    MS_TOKEN: str
    MS_ATTR_CIS_REQUIRED: str = Field(default="ЧЗ")
    MS_BUNDLE_MARK_FLAG: str = Field(default="Комплект_маркируемый")
    MAX_COMPONENT_FETCH: int = Field(default=200)

    def ms_auth_header(self) -> str:
        t = self.MS_TOKEN.strip()
        return t if t.lower().startswith("bearer ") else f"Bearer {t}"
