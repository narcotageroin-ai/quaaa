# ms-cis-scanner (DataMatrix) → MoySklad customerorder.description

Мини‑приложение на **Streamlit** для упаковщиков: быстро сканировать **все DataMatrix‑коды маркировки** для комплектов/заказов и записывать их **в customerorder.description** в МойСклад.

## Что умеет
- Найти `customerorder` по номеру (поле `name` в МС).
- Загрузить состав заказа, **раскрыть комплекты (bundle)** в компоненты.
- Посчитать **сколько КМ нужно отсканировать**:
  - если bundle помечен как маркируемый (атрибут `MS_BUNDLE_MARK_FLAG`) → все компоненты считаются маркируемыми
  - иначе маркируемость компонента определяется boolean‑атрибутом `MS_ATTR_CIS_REQUIRED`
- Поле ввода/сканирования: коды вставляются/сканируются **по одному в строке**.
- Валидация:
  - уникальность (без дублей)
  - формат DataMatrix (мягкая проверка, но можно ужесточить)
  - совпадение количества (ожидаемое N vs. введено)
- Запись в `customerorder.description` блоком:
  ```
  [CIS]
  <код1>
  <код2>
  ...
  [/CIS]
  ```

## Запуск локально
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
streamlit run streamlit_app.py
```

## Деплой в Streamlit Cloud
- Залейте репо в GitHub
- Streamlit Cloud → New app → `streamlit_app.py`
- Settings → Secrets:
```toml
MS_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"
MS_TOKEN = "Bearer <MS_TOKEN>"
MS_ATTR_CIS_REQUIRED = "ЧЗ"
MS_BUNDLE_MARK_FLAG = "Комплект_маркируемый"
MAX_COMPONENT_FETCH = "200"
```

## Примечание по DataMatrix
Чаще всего КМ приходит как строка GS1, начинающаяся с `01` и содержащая `21`.
Валидация в приложении **мягкая** (не режет работу), но предупреждает.
