from TierListBot.cogs.tierlist import TierListCog


def test_add_prompt_title_single_image():
    assert TierListCog._add_prompt_title(1, 1) == "Which tier?"


def test_add_prompt_title_multiple_images():
    assert TierListCog._add_prompt_title(2, 4) == "Which tier? (image 2 of 4)"
