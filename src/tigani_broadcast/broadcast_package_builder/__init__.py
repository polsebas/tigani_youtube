"""Ensamblado del paquete portable OBS 16:9 a partir de chapters/charts/assets."""

from tigani_broadcast.broadcast_package_builder.assemble import (
    KIND_PRIORITY,
    PackageValidationError,
    assemble_broadcast_package,
    collect_data_sources,
    collect_visual_credits,
    validate_package_inputs,
)
from tigani_broadcast.broadcast_package_builder.cli import (
    EXIT_ERROR,
    EXIT_OK,
    PackageBuilderCliError,
    main,
    run_cli,
)
from tigani_broadcast.broadcast_package_builder.deck import (
    render_chapter_cover_html,
    render_deck_html,
    write_deck_files,
)
from tigani_broadcast.broadcast_package_builder.models import (
    BroadcastPackageManifest,
    DataSourceCredit,
    ExcludedErrorRecord,
    PackageSlide,
    SlideKind,
    VisualLicenseCredit,
)
from tigani_broadcast.broadcast_package_builder.publishing import (
    render_rundown_markdown,
    render_social_post,
    render_youtube_description,
    write_publishing_files,
)

__all__ = [
    "EXIT_ERROR",
    "EXIT_OK",
    "KIND_PRIORITY",
    "BroadcastPackageManifest",
    "DataSourceCredit",
    "ExcludedErrorRecord",
    "PackageBuilderCliError",
    "PackageSlide",
    "PackageValidationError",
    "SlideKind",
    "VisualLicenseCredit",
    "assemble_broadcast_package",
    "collect_data_sources",
    "collect_visual_credits",
    "main",
    "render_chapter_cover_html",
    "render_deck_html",
    "render_rundown_markdown",
    "render_social_post",
    "render_youtube_description",
    "run_cli",
    "validate_package_inputs",
    "write_deck_files",
    "write_publishing_files",
]
