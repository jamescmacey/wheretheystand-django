"""Pipeline recipe registry."""

from __future__ import annotations

from .credit_card import CreditCardReconciliationRecipe
from .ministerial_list import MinisterialListRecipe
from .user_profile_pictures import UserProfilePicturesRecipe

PIPELINE_RECIPE_REGISTRY = {
    CreditCardReconciliationRecipe.key: CreditCardReconciliationRecipe(),
    MinisterialListRecipe.key: MinisterialListRecipe(),
    UserProfilePicturesRecipe.key: UserProfilePicturesRecipe(),
}


def get_recipe(recipe_key: str):
    try:
        return PIPELINE_RECIPE_REGISTRY[recipe_key]
    except KeyError as exc:
        raise ValueError(f"Unknown recipe_key '{recipe_key}'.") from exc
