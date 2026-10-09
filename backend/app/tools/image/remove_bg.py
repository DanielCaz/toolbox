from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image


class RemoveBgParams(BaseModel):
    model: Literal["u2netp", "u2net", "isnet-general-use"] = Field(
        "u2netp",
        description="u2netp = small and fast · u2net / isnet = more detail. "
        "Downloaded on first use.",
    )
    background: Literal["transparent", "white"] = Field(
        "transparent", description="What to put behind the subject"
    )


class RemoveBackground(Tool):
    id = "image.remove_bg"
    name = "Remove image background"
    category = "image"
    description = "Cut the subject out of a photo, on this machine (no upload to a web service)."
    accepts = ["image/*"]
    batch = True
    slow = True
    requires_py = ["rembg", "onnxruntime"]
    Params = RemoveBgParams

    def run(self, files: list[Path], params: RemoveBgParams, ctx: ToolContext):
        import os

        src = files[0]
        im, _ = open_image(src)
        models = get_settings().models_dir
        models.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("U2NET_HOME", str(models))  # must be set before rembg loads models
        from rembg import new_session, remove  # optional dependency

        ctx.progress(0.2, "Loading the model")
        try:
            session = new_session(params.model)
        except Exception as exc:
            raise ToolError(f"Could not load the '{params.model}' model: {exc}") from None
        ctx.check_cancelled()
        ctx.progress(0.5, "Removing the background")
        cut = remove(im.convert("RGB"), session=session).convert("RGBA")
        if params.background == "white":
            from PIL import Image

            flat = Image.new("RGB", cut.size, (255, 255, 255))
            flat.paste(cut, mask=cut.getchannel("A"))
            out = ctx.out_unique(f"{src.stem}-nobg.png")
            flat.save(out, "PNG")
        else:
            out = ctx.out_unique(f"{src.stem}-nobg.png")
            cut.save(out, "PNG")
        return [out]
