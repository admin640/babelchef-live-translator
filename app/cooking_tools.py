"""BabelChef Cooking Tools — callable by the translation agent mid-conversation.

These tools help bridge cultural cooking gaps:
- Measurement conversion (metric ↔ imperial ↔ Indian)
- Cooking timer suggestions
- Culturally-specific cooking term explanations
"""


def convert_measurement(
    value: float,
    from_unit: str,
    to_unit: str,
) -> str:
    """Convert between cooking measurement units across metric, imperial, and Indian systems.

    Supported units: cups, tablespoons (tbsp), teaspoons (tsp),
    grams (g), kilograms (kg), milliliters (ml), liters (l),
    ounces (oz), pounds (lb), fluid_ounces (fl_oz),
    pinch, dash, handful.

    Args:
        value: The numeric amount to convert.
        from_unit: The source unit (e.g., "cups", "grams", "tbsp").
        to_unit: The target unit (e.g., "ml", "oz", "tsp").

    Returns:
        A string with the converted measurement and a practical note.
    """
    # Normalize unit names
    unit_aliases = {
        "cup": "cups", "tablespoon": "tbsp", "tablespoons": "tbsp",
        "teaspoon": "tsp", "teaspoons": "tsp", "gram": "g", "grams": "g",
        "kilogram": "kg", "kilograms": "kg", "milliliter": "ml",
        "milliliters": "ml", "liter": "l", "liters": "l",
        "ounce": "oz", "ounces": "oz", "pound": "lb", "pounds": "lb",
        "fluid_ounce": "fl_oz", "fluid_ounces": "fl_oz",
    }

    src = unit_aliases.get(from_unit.lower().strip(), from_unit.lower().strip())
    dst = unit_aliases.get(to_unit.lower().strip(), to_unit.lower().strip())

    # All conversions go through ml (for volume) or grams (for weight)
    to_ml = {
        "cups": 236.588, "tbsp": 14.787, "tsp": 4.929,
        "ml": 1.0, "l": 1000.0, "fl_oz": 29.574,
        "pinch": 0.31, "dash": 0.62,
    }

    to_grams = {
        "g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592,
        "handful": 30.0,  # rough estimate
    }

    result_value = None
    if src in to_ml and dst in to_ml:
        result_value = value * to_ml[src] / to_ml[dst]
    elif src in to_grams and dst in to_grams:
        result_value = value * to_grams[src] / to_grams[dst]
    elif src in to_ml and dst in to_grams:
        # Approximate: 1 ml ≈ 1 g for water-based liquids
        ml_value = value * to_ml[src]
        result_value = ml_value * to_grams.get("g", 1.0) / to_grams[dst]
    elif src in to_grams and dst in to_ml:
        g_value = value * to_grams[src]
        result_value = g_value / to_ml[dst]

    if result_value is not None:
        # Round smartly
        if result_value >= 100:
            display = f"{result_value:.0f}"
        elif result_value >= 1:
            display = f"{result_value:.1f}"
        else:
            display = f"{result_value:.2f}"
        return f"{value} {from_unit} = {display} {to_unit}"
    else:
        return f"Cannot convert from {from_unit} to {to_unit}. Supported volume units: cups, tbsp, tsp, ml, l, fl_oz. Supported weight units: g, kg, oz, lb."


def cooking_timer_suggestion(
    item: str,
    method: str = "boil",
    doneness: str = "medium",
) -> str:
    """Suggest cooking time for common ingredients based on cooking method and desired doneness.

    Args:
        item: The ingredient (e.g., "rice", "chicken breast", "onions", "pasta").
        method: Cooking method (e.g., "boil", "fry", "bake", "sauté", "grill", "steam", "pressure_cook").
        doneness: Desired doneness (e.g., "soft", "medium", "crispy", "al_dente", "well_done").

    Returns:
        A string with the suggested cooking time and a brief tip.
    """
    # Common cooking times (minutes) — (min_time, max_time, tip)
    times = {
        ("rice", "boil"): (15, 20, "Cover and don't lift the lid. Let it rest 5 min after."),
        ("rice", "pressure_cook"): (4, 6, "Natural release for 10 min after cooking."),
        ("basmati rice", "boil"): (12, 15, "Soak 30 min first. Use 1.5x water ratio."),
        ("pasta", "boil"): (8, 12, "Salt the water generously. Test 1 min before package time."),
        ("chicken breast", "grill"): (6, 8, "Per side. Internal temp 165°F / 74°C."),
        ("chicken breast", "bake"): (20, 25, "At 400°F / 200°C. Let rest 5 min before cutting."),
        ("chicken breast", "fry"): (5, 7, "Per side on medium-high. Don't move it while searing."),
        ("onions", "sauté"): (5, 8, "Medium heat for translucent. 15-20 min for caramelized."),
        ("onions", "fry"): (8, 12, "Medium-high for golden brown. Stir frequently."),
        ("garlic", "sauté"): (1, 2, "Add after onions. Burns quickly — watch carefully!"),
        ("potatoes", "boil"): (15, 20, "Cubed. Start in cold water. Fork-tender when done."),
        ("potatoes", "bake"): (45, 60, "At 400°F / 200°C. Pierce with fork first."),
        ("eggs", "boil"): (6, 12, "6 min soft, 9 min medium, 12 min hard. Ice bath after."),
        ("paneer", "fry"): (2, 3, "Per side. Don't overcook or it gets rubbery."),
        ("dal", "pressure_cook"): (3, 5, "With 3x water. Natural release."),
        ("dal", "boil"): (25, 35, "Soak overnight for faster cooking. Skim foam."),
        ("naan", "bake"): (2, 3, "In very hot oven / tandoor. Should puff up."),
        ("chapati", "fry"): (1, 2, "Per side on dry tawa. Press gently for puffing."),
    }

    key = (item.lower().strip(), method.lower().strip())
    if key in times:
        min_t, max_t, tip = times[key]
        return f"{item} ({method}): {min_t}-{max_t} minutes. Tip: {tip}"

    # Fuzzy match on item name
    for (k_item, k_method), (min_t, max_t, tip) in times.items():
        if k_item in item.lower():
            return f"{item} ({k_method}): {min_t}-{max_t} minutes. Tip: {tip}"

    return f"No specific timing data for '{item}' ({method}). General rule: start checking early and adjust. Use a thermometer for meats."


def explain_cooking_term(
    term: str,
    target_culture: str = "general",
) -> str:
    """Explain a culturally-specific cooking term in simple, universal language.

    Useful when a term from one culinary tradition doesn't translate well.

    Args:
        term: The cooking term to explain (e.g., "tadka", "tempering", "beurre noisette", "soffritto").
        target_culture: The target audience culture (e.g., "indian", "western", "general").

    Returns:
        A clear, simple explanation of the technique or concept.
    """
    terms = {
        "tadka": "Tadka (also 'chaunk' or 'tempering'): Heat oil/ghee until very hot, then add whole spices (mustard seeds, cumin, curry leaves). They crackle and release flavor. Pour this sizzling spice oil over dal or curry at the end.",
        "tempering": "Tempering: Heating whole spices in hot oil/ghee until they crackle and pop, releasing their essential oils. Called 'tadka' in Indian cooking. The flavored oil is added to finish a dish.",
        "beurre noisette": "Beurre noisette (brown butter): Cook butter on medium heat until the milk solids turn golden-brown and it smells nutty. Takes about 3-4 minutes. Remove from heat immediately — it burns fast.",
        "soffritto": "Soffritto: The Italian flavor base — finely diced onion, carrot, and celery cooked slowly in olive oil until soft and golden (15-20 min). The French equivalent is 'mirepoix'.",
        "mirepoix": "Mirepoix: French flavor base of diced onion, carrot, and celery (2:1:1 ratio) cooked in butter. Similar to Italian 'soffritto' but uses butter instead of olive oil.",
        "mise en place": "Mise en place: French for 'everything in its place'. Prepare and measure ALL ingredients before you start cooking. Essential for complex recipes.",
        "deglazing": "Deglazing: After searing meat, add liquid (wine, broth, water) to the hot pan to dissolve the flavorful brown bits stuck to the bottom. These are called 'fond' and add deep flavor to sauces.",
        "blooming": "Blooming spices: Heating ground spices in hot oil or dry pan for 30-60 seconds until fragrant. This activates their essential oils and deepens the flavor. Don't burn them!",
        "dum": "Dum cooking: A slow-cooking technique where food is sealed in a heavy pot (often with dough around the lid) and cooked on very low heat. Used for biryani and some curries. The steam trapped inside cooks the food gently.",
        "bhunao": "Bhunao: Stir-frying spice paste (masala) on high heat, adding small splashes of water to prevent sticking, until the oil separates from the masala. This is the 'bhuna' stage — it concentrates flavors. Takes 10-15 min.",
        "chhaunk": "Chhaunk: Same as 'tadka' — tempering whole spices in hot oil. Regional Hindi term used in North India.",
        "jus": "Jus: A light sauce made from meat drippings, sometimes thickened slightly. Lighter than gravy, more flavorful than broth.",
        "al dente": "Al dente: Italian for 'to the tooth'. Pasta cooked until still slightly firm when bitten. Not mushy, not hard. About 1-2 minutes less than package instructions.",
        "roux": "Roux: Equal parts fat (butter) and flour cooked together. White roux (2 min) for béchamel, blonde roux (5 min) for velouté, dark roux (15-20 min) for gumbo.",
        "ghee": "Ghee: Clarified butter used in Indian cooking. Butter is simmered until water evaporates and milk solids turn golden, then strained. Higher smoke point than butter. Rich, nutty flavor.",
    }

    key = term.lower().strip()
    if key in terms:
        return terms[key]

    # Partial match
    for k, v in terms.items():
        if k in key or key in k:
            return v

    return f"'{term}' — I don't have a specific definition for this term. It may be a regional cooking technique. Try asking the other cook to demonstrate it on camera!"


# Export the tools list for use in ADK Agent
cooking_tools = [convert_measurement, cooking_timer_suggestion, explain_cooking_term]
