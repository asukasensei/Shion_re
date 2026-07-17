from agent.deal_response import DealResponse


def test_short_sentence_is_preserved_until_flush() -> None:
    output: list[str] = []
    response = DealResponse(output.append)

    response.feed("你好。")
    response.flush()

    assert output == ["你好。"]


def test_short_prefix_is_combined_with_following_sentence() -> None:
    output: list[str] = []
    response = DealResponse(output.append)

    response.feed("嗯。今天很开心！")
    response.flush()

    assert output == ["嗯。今天很开心！"]
