from app.utils.templates import render_template, validate_template


def validate_campaign_template(template: str) -> None:
    validate_template(template)


def render_campaign_message(
    template: str,
    username: str,
    campaign_name: str,
    keyword: str,
    link: str | None,
    media_url: str | None,
) -> str:
    context = {
        "username": username,
        "campaign_name": campaign_name,
        "keyword": keyword,
        "link": link or "",
        "media_url": media_url or "",
    }
    return render_template(template, context)
