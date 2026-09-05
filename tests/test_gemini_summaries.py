from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.gemini_service import GeminiService


def configured_service(response_text: str) -> tuple[GeminiService, MagicMock]:
    model = MagicMock()
    model.generate_content.return_value = SimpleNamespace(text=response_text)

    service = GeminiService()
    service._configured = True
    service._model = model
    return service, model


def test_album_summary_requests_brazilian_portuguese() -> None:
    service, model = configured_service("Um resumo em português.")

    result = service.generate_album_summary(
        title="1989",
        artist="Taylor Swift",
        release_date="2014-10-27",
        tracks=[{"name": "Blank Space"}],
        label="Big Machine Records",
    )

    prompt = model.generate_content.call_args.args[0]
    assert result == "Um resumo em português."
    assert "somente em português do Brasil" in prompt
    assert "Não traduza nomes próprios, títulos de álbuns ou nomes de faixas" in prompt
    assert "Álbum: 1989" in prompt
    assert "Faixas: Blank Space" in prompt


def test_artist_bio_requests_brazilian_portuguese_and_removes_markdown() -> None:
    service, model = configured_service("## Taylor Swift\n\n**Artista** americana.")

    result = service.generate_artist_bio(
        name="Taylor Swift",
        genres=["pop"],
        popularity=100,
    )

    prompt = model.generate_content.call_args.args[0]
    assert result == "Taylor Swift\n\nArtista americana."
    assert "somente em português do Brasil" in prompt
    assert "Produza somente texto simples" in prompt
    assert "Artista: Taylor Swift" in prompt
