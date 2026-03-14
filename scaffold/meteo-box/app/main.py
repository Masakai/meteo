from fastapi import FastAPI

app = FastAPI(title="meteo-box")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
