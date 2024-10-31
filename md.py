
def mdParse(content, is_slack):
    estr = ""

def convertLinks(content, is_slack):
    if is_slack:
        found_links = content.split('<')
        for raw in found_links:
            if raw.startsWith('http') != True:
                pass
            content = content.replace("<"+raw.split('>')[0]+ ">",  f'\[{raw.split('|')[1].split('>')[0]}\]\({raw.split("|")[0]}\)')
        return content

examplestrlinks = " txtbeforelink0 <https://saahild.com|test content> txtafterlink0 txtbef1 <https://zeon.saahild.com|zeon> txtaft1"
print(convertLinks(examplestrlinks, True))