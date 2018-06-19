

def merge_container_settings(merge_into, merge, clear_settings = True):
    if merge == merge_into:
        return

    for key in merge.getAllKeys():
        merge_into.setProperty(key, "value", merge.getProperty(key, "value"))

    if clear_settings:
        merge.clear()
