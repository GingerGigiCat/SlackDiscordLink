# This is mainly Zeon's contribution, not mine

def mdParse(content, is_slack):
    content = convertLinks(content, is_slack)
    content = convertBold(content, is_slack)
    if is_slack:
        content = content.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return content

def convertLinks(content, is_slack):

    if is_slack:
        found_links = content.split('<')
        for raw in found_links:
            try:
                if raw.startswith('http') != True:
                    continue
                content = content.replace("<"+raw.split('>')[0]+ ">",  f'[{raw.split('|')[1].split('>')[0]}]({raw.split("|")[0]})')
            except IndexError:
                pass
    else:
        found_links = content.split('[')
        for raw in found_links:
            try:
                if raw.split("(")[1].startswith("http") != True:
                    continue
                content = content.replace("[" + raw.split(")")[0] + ")", f"<{raw.split("(")[1].split(')')[0]}|{raw.split("]")[0]}>")
            except IndexError:
                pass
    return content

def convertBold(content, is_slack):
    if is_slack:
        found_links = content.split('*')
        i = 0
        for raw in found_links:
            if i % 2 != 0:
                content = content.replace(f'*{raw}*', f'**{raw}**')
            # print(i)
            i += 1
    else:
        found_links = content.split('**')
        i = 0
        for raw in found_links:
            if i % 2 != 0:
                content = content.replace(f'**{raw}**', f'*{raw}*')
            #print(raw)
            i += 1
    return content
    pass
# examplestrSlack = " txtbeforelink0 <https://saahild.com|test content> txtafterlink0 txtbef1 <https://zeon.saahild.com|zeon> txtaft1 *Bold text* *bt2*"
# print(mdParse(examplestrSlack, True))
