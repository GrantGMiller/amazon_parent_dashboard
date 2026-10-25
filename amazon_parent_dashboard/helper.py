def get_cookie_dict(cookie_string:str):
    splits = cookie_string.split(";")
    cookie_dict = {}
    for this_split in splits:
        sub_split = this_split.split('=')
        if len(sub_split) == 3: # sometimes there is an = at end of a base64 string
            key = sub_split[0]
            value = sub_split[1] + sub_split[2]
        else:
            key, value = sub_split
        cookie_dict[key.strip()] = value.strip()
    return cookie_dict