import main


def _entry(folder, video_id, mtime):
    name = f"Lesson [{video_id}].webm"
    return {
        "name": name,
        "rel": f"Espanol/{folder}/{name}",
        "size": 1,
        "mtime": mtime,
        "has_video": True,
        "channel": "Espanol",
        "subs": {},
    }


def test_latest_entries_track_channel_subfolder_visibility():
    first = _entry("Beginner", "abcdefghijk", 2)
    second = _entry("Intermediate", "bcdefghijkl", 1)
    page = main.generate_index_html(
        {"Espanol": [first, second]}, 2, 1, "now", "fp",
        latest=[first, second],
    )

    # The two Latest copies identify their source subfolders.
    assert page.count('data-channel="Espanol" data-sub="Beginner"') == 1
    assert page.count('data-channel="Espanol" data-sub="Intermediate"') == 1

    # Latest consults subgroup state, and a subgroup toggle reapplies it.
    assert 'var key = li.dataset.channel + "|" + (li.dataset.sub || "");' in page
    assert "!!(subState[key] || {}).collapsed" in page
    toggle = page.index('if (fb) fb.addEventListener("click"')
    assert "applyLatestVisibility();" in page[toggle:toggle + 500]
