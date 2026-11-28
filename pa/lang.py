"""Reply in the user's language: a task given in English gets an English reply, a task given in
Hinglish (Hindi in Latin letters, mixed with English) gets a Hinglish reply.

    detect(text, previous)  -> "en" | "hi"   (neutral input like "yes", "2", "5 pm" keeps `previous`)
    localize(text, lang)    -> the reply in that language

The replies are written once in the code (some in English, some in Hinglish). PAIRS below holds
both versions of each one, with {0}, {1}... for the parts that change (names, times, numbers).
localize() looks for the reply (or, line by line / sentence by sentence, its pieces) on either
side and returns the other side. Text without a pair is left as it is, so a missing pair never
breaks a reply. Pure Python, tested on a PC (tests/test_pa.py: ReplyLanguage).
"""
import re

# ---------- which language is the task in ----------
# Hindi words that do not occur in English sentences (names like mummy/papa/didi are not markers:
# "call mummy" is English).
HI_WORDS = frozenset("""
hai hain ho hoga hogi hoge hua hui hue tha thi karo kar kro krdo kardo karna karni karne karke kariye kijiye karu
karun kru kya kyu kyun kyon kaise kaisa kaisi kitni kitna kitne kab kahan kidhar kaun kaunsa kaunse konsa kisko kise
kisne ko pe par mein mai mujhe mera meri mere hamara humara apna apni apne tum tera teri aap aapka aapki aaj parso
baje bje subah shaam sham raat dopahar abhi phir fir aur nahi nahin nhi haan han haa hanji ji theek thik acha accha
achha bhejo bhej bhejna bhejdo bheju bhejun batao bata btao bataun bolo bol dikhao dikha dikhado kholo khol kholna
lagao laga lgao lagado chalao chalu yaad dilana dilao dila wala wali wale liye ki ka ke se tak sab kuch koi hoon hu
hun raha rahi rahe gaya gayi gaye diya dena dedo suno sunao chahiye lena jao jana chalo yaar bhaiya hatao hata mitao
likho likh padho padh bajao baja rakho rakh dekho dekh samjhao poocho pucho mat matlab woh wo yeh isko usko inko
unko iska uska kal kitni bharna peena khana jagana uthana bhoolna nikalo karwao chahta chahti pata
""".split())
# English words that show the task is in English (when no Hindi word is there)
EN_WORDS = frozenset("""
the a an to on in at for of is are am was were be what when where who whom how why which my me i you your it its this
that these those please can could would will should do does did set send open call show tell add remind turn make
play search find delete remove give get check list today tomorrow yesterday morning evening night afternoon time
date day saying say with and or from after before now then every all any some much many there here about
wake start stop go click tap type press read left want need like
""".split())


def _words(text):
    return re.findall(r"[a-z']+", (text or "").lower())


def detect(text, previous="en"):
    """'hi' if the task has Hindi words, 'en' if it has English ones, else the previous language."""
    words = _words(text)
    if any(w in HI_WORDS for w in words):
        return "hi"
    if any(w in EN_WORDS for w in words):
        return "en"
    return previous if previous in ("en", "hi") else "en"


# ---------- the two versions of each reply: (English, Hinglish) ----------
PAIRS = [
    # general
    ("Please type something.", "Kuch likho to sahi."),
    ("Okay, nothing was done.", "Theek hai, kuch nahi kiya."),
    ("Sorry, I did not understand that. Try:", "Sorry, main samjha nahi. Aise bolo:"),
    ("Sorry, I did not understand that.", "Sorry, main samjha nahi."),
    ("This is not supported yet ({0}): no adapter is implemented.", "Ye abhi support nahi hai ({0})."),
    ("This option is no longer valid. Please ask again.", "Ye option ab valid nahi hai. Dobara bolo."),
    ("Approve?", "Approve karun?"),
    ("Failed: {0}", "Nahi hua: {0}"),
    ("{0} {1} ({2}) again? Say 1 or yes.", "{1} ({2}) ko dobara {0} karun? 1 ya haan bolo."),
    # small talk / help
    ("{0}! I am Lazey. What can I do? Try: call mummy / how much battery is left / remind me tomorrow at 5.",
     "{0}! Main Lazey hoon. Kya karun? Try: call mummy / battery kitni hai / kal 5 baje yaad dilana."),
    ("I am doing well, thanks! What should I do for you?", "Main badhiya hoon, shukriya! Aap batao, kya karna hai?"),
    ("You're welcome! Tell me if you need anything else.", "Koi baat nahi! Aur kuch chahiye to bolo."),
    ("Bye! Call me when you need me.", "Bye! Zaroorat ho to bula lena."),
    ("Okay. Anything else?", "Okay. Aur kuch?"),
    ("I am Lazey, your offline personal assistant. I help with calls, messages, alarms, reminders, notes and phone "
     "status.",
     "Main Lazey hoon, aapka offline personal assistant. Call, message, alarm, reminders, notes aur phone status mein "
     "madad karta hoon."),
    ("Here is what I can do (say it in English or Hinglish):", "Main yeh kar sakta hoon (English ya Hinglish mein bolo):"),
    ("- call mummy / call rahul on whatsapp", "- call mummy / rahul ko whatsapp pe call karo"),
    ("- send rahul a message saying I am late", "- rahul ko message bhejo ki main late hoon"),
    ("- set an alarm for 6 am / set a timer for 10 minutes", "- alarm laga do subah 6 baje / 10 minute ka timer"),
    ("- remind me tomorrow at 5 to pay the bill / show my todos",
     "- kal 5 baje yaad dilana ki bill bharna hai / mere todo dikhao"),
    ("- note: ... / remember that ...", "- note karo: ... / yaad rakho ..."),
    ("- how much battery is left / what time is it", "- battery kitni hai / what time is it"),
    ("- open whatsapp / show yesterday's photos", "- open whatsapp / kal ki photos dikhao"),
    ("- phone control (after you approve): open youtube then search lofi / open whatsapp then click rahul then type hi "
     "/ go back / go home",
     "- phone control (Approve ke baad): youtube kholo phir lofi search karo / whatsapp kholo phir rahul pe click karo "
     "phir hi type karo / back jao / home jao"),
    # memory / notes
    ("What should I remember?", "Kya yaad rakhun?"),
    ("This sounds temporary, so I did not save it as a permanent preference.",
     "Ye temporary lag raha hai, isliye maine ise hamesha ki preference nahi banaya."),
    ("Preference saved: {0}", "Preference save ho gayi: {0}"),
    ("What should the note say?", "Note mein kya likhun?"),
    ("Note saved.", "Note save ho gaya."),
    ("No matching note found.", "Aisa koi note nahi mila."),
    ("Your notes:", "Aapke notes:"),
    # planning work time
    ("I need these details: {0}", "Mujhe ye details chahiye: {0}"),
    ("What time do you want to work? (morning / afternoon / evening or HH:MM)",
     "Kis time kaam karna hai? (subah / dopahar / shaam ya HH:MM)"),
    ("No free slot found: {0}", "Koi khaali time nahi mila: {0}"),
    ("Calendar is not available on this device.", "Is device par calendar nahi hai."),
    ("Invalid plan: {0}", "Plan sahi nahi hai: {0}"),
    ("(Note: could not check calendar availability; only checked overlap with in-app tasks.)",
     "(Note: calendar check nahi ho paya; sirf app ke tasks se takraav dekha.)"),
    ("Calendar event: '{0}' on {1}, {2}-{3}", "Calendar event: '{0}', {1}, {2}-{3}"),
    ("Calendar event created.", "Calendar event ban gaya."),
    ("The calendar screen is open. The event is created only when you tap Save there. The task is saved in the app.",
     "Calendar screen khuli hai. Wahan Save dabane par hi event banega. Task app mein save ho gaya."),
    # calls
    ("Who should I call on WhatsApp?", "WhatsApp pe kisko call karun?"),
    ("Whom should I call on WhatsApp?", "WhatsApp pe kisko call karun?"),
    ("WhatsApp calls are not available on this device.", "Is device par WhatsApp call nahi ho sakti."),
    ("WhatsApp calls need permission to read contacts. Allow it and say the same thing again.",
     "WhatsApp call ke liye contacts padhne ki permission chahiye. Allow karke wahi dobara bolo."),
    ("Could not read contacts: {0}", "Contacts nahi padh paya: {0}"),
    ("No contact found for '{0}'. No call was made.", "'{0}' naam ka contact nahi mila. Call nahi ki."),
    ("No contact found for {0}. No call was made.", "{0} naam ka contact nahi mila. Call nahi ki."),
    ("Starting a WhatsApp {0} call with {1}.", "{1} ko WhatsApp {0} call laga raha hoon."),
    ("WhatsApp has no call entry for {0} (not on WhatsApp, or not synced yet). Opened the chat: tap the {1} call button.",
     "WhatsApp mein {0} ki call entry nahi hai (WhatsApp par nahi hain, ya abhi sync nahi hua). Chat khol di hai: {1} "
     "call button dabao."),
    ("{0} does not seem to be on WhatsApp. No call was made.", "{0} WhatsApp par nahi lag rahe. Call nahi ki."),
    ("Could not start the WhatsApp call: {0}. No call was made.", "WhatsApp call shuru nahi hui: {0}. Call nahi ki."),
    ("Who should I call? Type a name or number.", "Kisko call karun? Naam ya number likho."),
    ("Calling is not available on this device.", "Is device se call nahi ho sakti."),
    ("Contacts are not available on this device. Please say the number instead.",
     "Is device par contacts nahi hain. Number bolo."),
    ("Direct calls need Contacts, Phone and SIM permissions. Please allow them and try again.",
     "Seedhi call ke liye Contacts, Phone aur SIM permissions chahiye. Allow karke dobara try karo."),
    ("No contact is named exactly {0}. These are similar. Who should I call?",
     "Bilkul {0} naam ka contact nahi hai. Ye milte-julte hain. Kisko call karun?"),
    ("Found {0}: {1} contacts. Who should I call?{2}", "{0} ke {1} contacts mile. Kisko call karun?{2}"),
    ("(Tip: you can also say the first 4 digits of the number.)", "(Tip: number ke pehle 4 digit bhi bol sakte ho.)"),
    ("Could not find the SIM '{0}'. SIMs in this phone: {1}. No call was made.",
     "SIM '{0}' nahi mila. Is phone ke SIM: {1}. Call nahi ki."),
    ("Calling {0} ({1}){2}.", "{0} ({1}) ko call kar raha hoon{2}."),
    ("from SIM {0} ({1})", "SIM {0} ({1}) se"),
    ("Dialer opened ({0}). Tap the call button to call.", "Dialer khul gaya ({0}). Call button dabao."),
    ("Call failed: {0}", "Call nahi hui: {0}"),
    ("The number does not look right: {0}. No call was made.", "Number sahi nahi lag raha: {0}. Call nahi ki."),
    ("Call started ({0}).", "Call shuru ({0})."),
    ("Dialer opened with the number filled in. Tap the call button to call.",
     "Dialer mein number bhar diya hai. Call button dabao."),
    ("No call was made.", "Call nahi ki."),
    ("No message was sent.", "Message nahi bheja."),
    # apps
    ("Which app should I open?", "Kaunsa app kholun?"),
    ("Opening apps is not available on this device.", "Is device par app nahi khul sakte."),
    ("Could not read the app list: {0}", "Apps ki list nahi padh paya: {0}"),
    ("No app called '{0}' found on this phone.", "Is phone par '{0}' naam ka app nahi mila."),
    ("Found {0} apps for '{1}'. Which one should I open?", "'{1}' ke {0} apps mile. Kaunsa kholun?"),
    ("Opening {0}.", "{0} khol raha hoon."),
    ("Could not open {0}: {1}", "{0} nahi khula: {1}"),
    # phone status
    ("It is {0}, {1}.", "Abhi {0} hai, {1}."),
    ("Phone status is not available on this device.", "Is device par phone status nahi mil sakta."),
    ("Could not read the {0}: {1}", "{0} nahi padh paya: {1}"),
    ("Battery: {0}%, not charging{1}.", "Battery: {0}%, charge nahi ho rahi{1}."),
    ("Battery: {0}%, charging{1}.", "Battery: {0}%, charge ho rahi hai{1}."),
    ("Battery is low: charge the phone soon.", "Battery kam hai: jaldi charge karo."),
    ("The battery is hot: let it cool down.", "Battery garam hai: thoda thanda hone do."),
    ("Storage: {0} free of {1} ({2}% used).", "Storage: {1} mein se {0} khaali ({2}% bhara)."),
    ("Storage is almost full: delete old videos or apps you do not use.",
     "Storage lagbhag bhar gaya: purane videos ya bekaar apps delete karo."),
    ("RAM: {0} free of {1}, running low.", "RAM: {1} mein se {0} khaali, kam bachi hai."),
    ("RAM: {0} free of {1}.", "RAM: {1} mein se {0} khaali."),
    ("No internet right now. (This assistant works fully offline.)",
     "Abhi internet nahi hai. (Ye assistant poori tarah offline chalta hai.)"),
    ("Online via {0}.", "{0} se online hai."),
    ("No alarm is set.", "Koi alarm set nahi hai."),
    ("Next alarm: {0} {1}.", "Agla alarm: {0} {1}."),
    # to-dos and reminders
    ("What should I remind you about? Example: remind me at 6 pm to drink water",
     "Kis baat ki yaad dilaun? Example: shaam 6 baje yaad dilana ki paani peena hai"),
    ("That time has already passed. Nothing was added.", "Wo time nikal chuka hai. Kuch add nahi kiya."),
    ("Reminders are not available on this device.", "Is device par reminders nahi hain."),
    ("Reminders need permission to show notifications. Allow it and say the same thing again.",
     "Reminders ke liye notifications ki permission chahiye. Allow karke wahi dobara bolo."),
    ("Could not set the reminder: {0}", "Reminder set nahi hua: {0}"),
    ("Reminder set for {0} {1}: {2}", "Reminder set: {0} {1}: {2}"),
    ("Added to your to-do list: {0}.{1}", "To-do list mein add kiya: {0}.{1}"),
    ("Say a time to get a notification, e.g. 'remind me at 6 pm to {0}'.",
     "Notification chahiye to time bolo, jaise 'shaam 6 baje yaad dilana ki {0}'."),
    ("Your to-dos:", "Aapke to-dos:"),
    ("Your to-do list is empty.", "Aapki to-do list khaali hai."),
    ("Which to-do is done? Say its number from 'show my todos'.",
     "Kaunsa to-do ho gaya? 'mere todo dikhao' wali list se uska number bolo."),
    ("No open to-do matches that.", "Aisa koi khula to-do nahi mila."),
    ("Several to-dos match. Say its number from 'show my todos'.",
     "Kai to-dos milte hain. 'mere todo dikhao' wali list se number bolo."),
    ("That to-do is already done.", "Wo to-do pehle hi ho chuka hai."),
    ("Done: {0}", "Ho gaya: {0}"),
    # day plan
    ("Plan for {0} ({1}):", "{0} ka plan ({1}):"),
    ("- alarm at {0}", "- {0} ka alarm"),
    ("- battery is {0}%: charge the phone", "- battery {0}% hai: phone charge karo"),
    ("- nothing planned yet", "- abhi kuch plan nahi hai"),
    ("Suggestion: do '{0}' at {1}-{2} (first free 30 minutes{3}).",
     "Suggestion: '{0}' {1}-{2} par karo (pehle khaali 30 minute{3})."),
    ("Suggestion: no free 30 minutes left {0} for '{1}'; move it to another day.",
     "Suggestion: {0} '{1}' ke liye 30 minute khaali nahi bache; kisi aur din rakho."),
    ("(Calendar not checked: no permission.)", "(Calendar check nahi kiya: permission nahi hai.)"),
    # routines
    ("Your routines:", "Aapke routines:"),
    ("No routines yet. Example: routine good morning: set an alarm for 7 am; open whatsapp",
     "Abhi koi routine nahi hai. Example: routine good morning: set an alarm for 7 am; open whatsapp"),
    ("No routine called '{0}'. Your routines: {1}.", "'{0}' naam ka koi routine nahi hai. Aapke routines: {1}."),
    ("No routine called '{0}'.", "'{0}' naam ka koi routine nahi hai."),
    ("Deleted routine '{0}'.", "Routine '{0}' delete kar diya."),
    ("I do not understand these steps, so the routine was not saved: {0}",
     "Ye steps samajh nahi aaye, isliye routine save nahi kiya: {0}"),
    ("Saved routine '{0}' ({1} step{2}):", "Routine '{0}' save ho gaya ({1} step):"),
    ("Say '{0} routine' or just '{1}' to run it. To run it at a time: '{2} routine har din 7 baje'.",
     "Chalane ke liye '{0} routine' ya sirf '{1}' bolo. Kisi time par chalane ke liye: '{2} routine har din 7 baje'."),
    ("Timed routines are not available on this device.", "Is device par timed routines nahi hain."),
    ("Timed routines need permission to show notifications. Allow it and say the same thing again.",
     "Timed routines ke liye notifications ki permission chahiye. Allow karke wahi dobara bolo."),
    ("Could not schedule the routine: {0}", "Routine schedule nahi hua: {0}"),
    ("Every {0} at {1} you will get a notification 'Routine: {2}'. Tap it and the routine runs.",
     "Har {0} {1} baje notification aayega 'Routine: {2}'. Use tap karo, routine chal jayega."),
    ("Important: allow Lazey to run in the background on the next screen, or your phone may cancel it.",
     "Zaroori: agli screen par Lazey ko background mein chalne do, warna phone ise cancel kar sakta hai."),
    ("Routine '{0}' has no set time.", "Routine '{0}' ka koi time set nahi hai."),
    ("Routine '{0}' will no longer run at a set time (you can still say it).",
     "Routine '{0}' ab kisi time par apne aap nahi chalega (bolkar ab bhi chala sakte ho)."),
    ("Routine '{0}' done:", "Routine '{0}' ho gaya:"),
    ("(Stopped here. Not run yet: {0})", "(Yahan ruk gaya. Abhi nahi chale: {0})"),
    ("Not run because another app is already open: {0}. Say them after you come back.",
     "Nahi chale kyunki ek aur app pehle se khula hai: {0}. Waapas aakar bolo."),
    ("(Started from the routine notification)", "(Routine notification se shuru hua)"),
    # alarms / timers
    ("Alarms are not available on this device.", "Is device par alarm nahi hai."),
    ("Opening your alarms.", "Aapke alarms khol raha hoon."),
    ("Could not open the alarms: {0}", "Alarms nahi khule: {0}"),
    ("For how long? Example: 10 minutes", "Kitni der ka? Example: 10 minute"),
    ("Could not set the timer: {0}", "Timer set nahi hua: {0}"),
    ("Timer set for {0}.", "{0} ka timer set ho gaya."),
    ("What time should the alarm ring? Example: 5 am", "Alarm kitne baje bajna chahiye? Example: subah 5 baje"),
    ("Could not set the alarm: {0}", "Alarm set nahi hua: {0}"),
    ("Alarm set for {0} every day in your Clock app.", "Clock app mein roz {0} ka alarm set ho gaya."),
    ("Alarm set for {0} in your Clock app.", "Clock app mein {0} ka alarm set ho gaya."),
    # WhatsApp auto-send
    ("WhatsApp auto-send works only in the phone app.", "WhatsApp auto-send sirf phone wale app mein chalta hai."),
    ("Yes, WhatsApp auto-send is ON: after I open a chat with your message typed, I press Send for you. (To switch it "
     "off: tap 'Auto-send settings'.)",
     "Haan, WhatsApp auto-send ON hai: message type karke chat kholne ke baad Send main dabata hoon. (Band karne ke "
     "liye: 'Auto-send settings' dabao.)"),
    ("No, WhatsApp auto-send is OFF, so WhatsApp messages wait for you to press Send. Tap 'Turn on auto-send' to "
     "switch it on.",
     "Nahi, WhatsApp auto-send OFF hai, isliye WhatsApp messages par Send aapko dabana hoga. On karne ke liye 'Turn "
     "on auto-send' dabao."),
    ("WhatsApp message sent to {0}.", "{0} ko WhatsApp message chala gaya."),
    ("WhatsApp opened but the Send press did not work. Please press Send yourself.",
     "WhatsApp khula par Send nahi dab paya. Send khud daba do."),
    ("Not sent: WhatsApp did not show the message in time (is {0} on WhatsApp?). Check the chat and press Send "
     "yourself.",
     "Nahi gaya: WhatsApp ne time par message nahi dikhaya (kya {0} WhatsApp par hain?). Chat dekho aur Send khud "
     "dabao."),
    ("WhatsApp auto-send is off (Android switches it off when the app is updated or force-stopped), so WhatsApp "
     "messages will wait for you to press Send. Turn it on again:",
     "WhatsApp auto-send band hai (app update ya force-stop hone par Android ise band kar deta hai), isliye WhatsApp "
     "messages par Send aapko dabana hoga. Dobara on karo:"),
    # messages now
    ("Sending this needs permission (read contacts). Allow it and say the same thing again.",
     "Iske liye contacts padhne ki permission chahiye. Allow karke wahi dobara bolo."),
    ("Sending this needs permission ({0}). Allow it and say the same thing again.",
     "Iske liye permission chahiye ({0}). Allow karke wahi dobara bolo."),
    ("What should the message to {0} say?", "{0} ko message mein kya likhun?"),
    ("Sending messages is not available on this device.", "Is device se message nahi bhej sakte."),
    ("How should I send it?", "Kaise bhejun?"),
    ("WhatsApp (you press Send)", "WhatsApp (Send aap dabaoge)"),
    ("WhatsApp (you tap Send)", "WhatsApp (Send aap dabaoge)"),
    ("SMS (sent automatically)", "SMS (apne aap chala jayega)"),
    ("No contact found for '{0}'. No message was sent.", "'{0}' naam ka contact nahi mila. Message nahi bheja."),
    ("Who should get the message?", "Message kisko bhejun?"),
    ("Send '{0}' to {1} ({2}) on WhatsApp? Say 1 or yes.", "{1} ({2}) ko WhatsApp pe '{0}' bhejun? 1 ya haan bolo."),
    ("Could not open WhatsApp: {0}", "WhatsApp nahi khula: {0}"),
    ("Sending on WhatsApp to {0}...", "{0} ko WhatsApp pe bhej raha hoon..."),
    ("Opening WhatsApp chat with {0}. The message is typed: press Send.",
     "{0} ki WhatsApp chat khol raha hoon. Message type hai: Send dabao."),
    ("To let the app press Send for you, tap 'Turn on auto-send'.",
     "Send app se dabwana hai to 'Turn on auto-send' dabao."),
    ("Sending SMS is not available on this device.", "Is device se SMS nahi bhej sakte."),
    ('Send SMS to {0} ({1}){2}: "{3}"', '{0} ({1}) ko SMS bhejna hai{2}: "{3}"'),
    ("SMS charges may apply.", "SMS ka charge lag sakta hai."),
    ("SMS handed to the phone for sending to {0}.", "{0} ko SMS bhejne ke liye phone ko de diya."),
    ("SMS permission is off, so nothing was sent.", "SMS permission band hai, isliye kuch nahi bheja."),
    # daily messages
    ("I can repeat a message every day or on chosen weekdays (e.g. 'har monday', 'weekdays'), but not monthly or "
     "hourly.",
     "Main message roz ya chune hue dinon par bhej sakta hoon (jaise 'har monday', 'weekdays'), par mahine ya ghante "
     "ke hisaab se nahi."),
    ('What should the message say? Example: send "Good morning" to mummy every day at 8 am.',
     'What should the message say? Example: har subah 8 baje mummy ko "Good morning" bhejo.'),
    ('At what time? Example: every day at 8 am send "Good morning" to mummy.',
     'Kitne baje? Example: har subah 8 baje mummy ko "Good morning" bhejo.'),
    ("Daily messages are not available on this device.", "Is device par daily messages nahi hain."),
    ("How should I send it every day?", "Roz kaise bhejun?"),
    ("Daily messages need permission to {0}. Allow it and say the same thing again.",
     "Daily messages ke liye permission chahiye ({0}). Allow karke wahi dobara bolo."),
    ("No contact found for '{0}'. Nothing was scheduled.", "'{0}' naam ka contact nahi mila. Kuch schedule nahi kiya."),
    ("Who should get the daily message?", "Daily message kisko bhejun?"),
    ("Cannot schedule this: {0}", "Ye schedule nahi ho sakta: {0}"),
    ("Each day you get a notification; tap it and press Send in WhatsApp.",
     "Roz ek notification aayega; use tap karke WhatsApp mein Send dabao."),
    ('Every {0} at {1}, {2} to {3} ({4}): "{5}"', 'Har {0} {1} baje, {3} ({4}) ko {2}: "{5}"'),
    ("Daily message scheduled for {0} every day. You can see or delete it under Tasks.",
     "Daily message roz {0} baje ke liye schedule ho gaya. Tasks mein dekh ya delete kar sakte ho."),
    ("Daily message scheduled. You can see or delete it under Tasks.",
     "Daily message schedule ho gaya. Tasks mein dekh ya delete kar sakte ho."),
    ("A permission is missing, so nothing was scheduled. Say it again and allow the permission.",
     "Ek permission missing hai, isliye kuch schedule nahi hua. Dobara bolo aur permission allow karo."),
    ("Important: allow Lazey to run in the background on the next screen, or your phone may stop daily messages after "
     "the first day.",
     "Zaroori: agli screen par Lazey ko background mein chalne do, warna phone pehle din ke baad daily messages rok "
     "sakta hai."),
    # automations (Menu > Automations)
    ("What should the daily reminder say? Example: every day at 9 am remind me to study",
     "Roz ke reminder mein kya likhun? Example: har din subah 9 baje yaad dilana ki padhna hai"),
    ("At what time? Example: every day at 9 am remind me to study",
     "Kitne baje? Example: har din subah 9 baje yaad dilana ki padhna hai"),
    ("At what time? Example: every day at 7 am open youtube then search lofi",
     "Kitne baje? Example: har din subah 7 baje youtube kholo phir lofi search karo"),
    ("Automations are not available on this device.", "Is device par automations nahi hain."),
    ("Could not save the automation: {0}", "Automation save nahi hua: {0}"),
    ('Automation saved: every {0} at {1} you get a reminder "{2}". See it in Menu > Automations.',
     'Automation save ho gaya: har {0} {1} baje reminder aayega "{2}". Menu > Automations mein dekh sakte ho.'),
    ("I can automate: reminders, messages, opening apps, phone-control steps and phone status. Example: every day "
     "at 7 am open youtube then search lofi",
     "Main ye automate kar sakta hoon: reminders, messages, apps kholna, phone-control steps aur phone status. "
     "Example: har din subah 7 baje youtube kholo phir lofi search karo"),
    ("Cannot save this automation: {0}", "Ye automation save nahi ho sakta: {0}"),
    ("Automation every {0} at {1}. At that time you get a notification; tap it and this runs:",
     "Automation har {0} {1} baje. Us time ek notification aayega; tap karte hi ye chalega:"),
    ("Automation saved. At its time you get a notification: tap it and it runs. See or delete it in Menu > "
     "Automations.",
     "Automation save ho gaya. Time par notification aayega: tap karte hi chalega. Menu > Automations mein dekh ya "
     "delete kar sakte ho."),
    ("Automations need permission to show notifications. Allow it and say the same thing again.",
     "Automations ke liye notifications ki permission chahiye. Allow karke wahi dobara bolo."),
    ("That automation was deleted, so nothing was run.", "Wo automation delete ho chuka hai, isliye kuch nahi chala."),
    ("Running the automation now. I will tell you how it went when you are back in Lazey.",
     "Automation chala raha hoon. Lazey mein waapas aaoge tab bataunga kaisa raha."),
    ("No automations yet. Examples: every day at 9 am remind me to study / every day at 7 am open youtube then "
     "search lofi",
     "Abhi koi automation nahi hai. Example: har din subah 9 baje yaad dilana ki padhna hai / har din subah 7 baje "
     "youtube kholo phir lofi search karo"),
    ("Your automations:", "Aapke automations:"),
    ("- every {0} at {1}: {2}", "- har {0} {1} baje: {2}"),
    ('Message to {0}: "{1}"', '{0} ko message: "{1}"'),
    ("(Started from the automation notification)", "(Automation notification se shuru hua)"),
    # photos
    ("Photos are not available on this device.", "Is device par photos nahi hain."),
    ("I need permission to see your photos. Please allow it and try again.",
     "Photos dekhne ki permission chahiye. Allow karke dobara try karo."),
    ("Could not read photos: {0}", "Photos nahi padh paya: {0}"),
    ("No photos found ({0}).{1}", "Koi photo nahi mili ({0}).{1}"),
    ("(Only showing the photos you gave access to.)", "(Sirf wahi photos dikha raha hoon jinki permission di hai.)"),
    ("Found {0} photos ({1}). Newest {2}:{3}", "{0} photos mili ({1}). Nayi {2}:{3}"),
    ("This photo is no longer in the list. Please search again.", "Ye photo ab list mein nahi hai. Dobara search karo."),
    ("Opened the photo in the gallery/viewer.", "Photo gallery mein khol di."),
    ("Could not open the photo: {0}", "Photo nahi khuli: {0}"),
    # approval
    ("Rejected. Nothing changed.", "Reject kar diya. Kuch nahi badla."),
    ("This action can no longer be rejected.", "Ye kaam ab reject nahi ho sakta."),
    ("Android permission was not given. Nothing changed.", "Android permission nahi mili. Kuch nahi badla."),
    ("This action was already done.", "Ye kaam pehle hi ho chuka hai."),
    ("The action changed, so it was not approved. Please ask again.",
     "Kaam badal gaya, isliye approve nahi hua. Dobara bolo."),
    ("This is not supported on this device.", "Ye is device par support nahi hai."),
    # phone control
    ("Phone control works only in the phone app.", "Phone control sirf phone wale app mein chalta hai."),
    ("In which app? First say the step that opens the app, e.g. 'open youtube then search lofi' or 'open whatsapp "
     "then click rahul'.",
     "Kaunse app mein? Pehle app kholne ka step bolo, jaise: 'youtube kholo phir lofi search karo' ya 'whatsapp kholo "
     "phir rahul pe click karo'."),
    ("Several apps match '{0}': {1}. Say the full name.", "'{0}' se kai apps milte hain: {1}. Poora naam bolo."),
    ("Phone control does not work in {0}: on this phone Android switches 'Lazey phone control' off as soon as Settings "
     "opens. I can only open Settings: 'open settings'.",
     "{0} mein phone control kaam nahi karta: is phone par Settings khulte hi Android 'Lazey phone control' band kar "
     "deta hai. Settings ko main sirf khol sakta hoon: 'settings kholo'."),
    ("This needs 'Lazey phone control' to be on (Settings > Accessibility). Tap 'Turn on phone control', switch it "
     "on, then say the steps again.",
     "Iske liye 'Lazey phone control' on karna hoga (Settings > Accessibility). Tap 'Turn on phone control', switch it "
     "on, then say the steps again."),
    ("Phone control is not available on this device.", "Is device par phone control nahi hai."),
    ("These steps cannot run: {0}", "Ye steps nahi chal sakte: {0}"),
    ("Running the steps now. I will tell you how it went when you are back in Lazey.",
     "Steps chala raha hoon. Lazey mein waapas aaoge tab bataunga kaisa raha."),
    ("'Lazey phone control' is off, so nothing was done. Turn it on in Settings > Accessibility and say the steps "
     "again.",
     "'Lazey phone control' band hai, isliye kuch nahi kiya. Settings > Accessibility mein on karke steps dobara "
     "bolo."),
    ("Done: the step.", "Ho gaya: step poora hua."),
    ("Done: all {0} steps.", "Ho gaya: saare {0} steps poore hue."),
    ("Stopped at step {0} of {1}: {2}.", "Step {0} (kul {1}) par ruk gaya: {2}."),
    ("On the screen:", "Screen par:"),
    ("Found {1} chats with this name on {0}. Which one should get it? (Nothing was sent.)",
     "{0} par is naam ki {1} chats mili. Kisko bhejna hai? (Kuch nahi bheja gaya.)"),
    # why phone control stopped (java/org/pa/assistant/PhoneControlService.java)
    ("Lazey was on the screen, not another app", "screen par Lazey tha, koi doosra app nahi"),
    ('could not find "{0}" on the screen', 'screen par "{0}" nahi mila'),
    ("could not find a search box", "search box nahi mila"),
    ('no chat named "{0}" in the list on the screen, so nothing was sent',
     'screen ki list mein "{0}" naam ki chat nahi mili, isliye kuch nahi bheja'),
    ("no text box on the screen to press Enter in", "screen par Enter dabane ke liye text box nahi hai"),
    ("no text box on the screen", "screen par text box nahi hai"),
    ("nothing to scroll on this screen", "is screen par scroll karne ko kuch nahi hai"),
    ("the app did not open the chat", "app ne chat nahi kholi"),
    ("the app did not open", "app nahi khula"),
    ('the chat on the screen is not with "{0}", so nothing was typed or sent',
     'screen wali chat "{0}" ki nahi hai, isliye kuch type ya send nahi kiya'),
    ("the message did not show up in the chat after Send, so it may not have been sent",
     "Send ke baad message chat mein nahi dikha, shayad nahi gaya"),
    ("the text box did not take the text", "text box ne text nahi liya"),
    ("the steps took too long", "steps mein bahut time lag gaya"),
    ("Android switched 'Lazey phone control' off (this phone does that while the Settings app is open)",
     "Android ne 'Lazey phone control' band kar diya (ye phone Settings khulne par aisa karta hai)"),
    ("Enter did not work", "Enter kaam nahi kiya"),
    ("back did not work", "back kaam nahi kiya"),
    ("home did not work", "home kaam nahi kiya"),
    ("cannot scroll further", "aur scroll nahi ho sakta"),
    ("could not open that chat", "wo chat nahi khuli"),
    ("notifications did not open", "notifications nahi khule"),
    ("recent apps did not open", "recent apps nahi khule"),
    ("that app cannot be opened", "wo app khul nahi sakta"),
    ("that app is not installed", "wo app install nahi hai"),
    ("that is a password field, so I did not type in it", "wo password field hai, isliye maine usme type nahi kiya"),
    ("the tap did not work", "tap kaam nahi kiya"),
    ("typing did not work", "typing kaam nahi ki"),
    ('did not tap "{0}"', '"{0}" pe tap nahi hua'),
    # social apps (Instagram, LinkedIn...) and email
    ("Example: save rahul's instagram as rahul_23", "Example: rahul ka instagram username rahul_23 hai"),
    ("'{0}' does not look like a valid email address.", "'{0}' sahi email address nahi lagta."),
    ("Saved {0}'s email {1}. Now say: 'email {2} saying ...'", "Saved: {0} ka email {1}. Ab bolo: '{2} ko mail karo ki ...'"),
    ("'{0}' is not a valid {1} username.", "'{0}' sahi {1} username nahi hai."),
    ("Saved {0}'s {1} {2} {3}. Now say: 'send hi to {4} on {5}'.",
     "Saved: {0} ka {1} {2} {3}. Ab bolo: '{4} ko {5} pe hi bhejo'."),
    ("No usernames saved. Example: save rahul's instagram as rahul_23",
     "Koi username saved nahi hai. Example: rahul ka instagram username rahul_23 hai"),
    ("Deleted {0}'s {1} {2}.", "Deleted {0} ka {1} {2}."),
    ("{0}'s {1} {2} was not saved.", "{0} ka {1} {2} saved nahi tha."),
    ("Who should get the email?", "Email kisko bhejna hai?"),
    ("I do not know {0}'s email address. Say once: 'save {1}'s email as <address>', then send again.",
     "Mujhe {0} ka email address nahi pata. Ek baar bolo: '{1} ka email <address> hai', phir dobara bhejo."),
    ("What should the email to {0} say?", "{0} ko email me kya likhna hai?"),
    ("Email works only in the phone app.", "Email sirf phone wale app mein chalta hai."),
    ("Gmail did not open: {0}", "Gmail nahi khula: {0}"),
    ("Opening Gmail: the email to {0} ({1}) is written. You press Send.",
     "Gmail khul raha hai: {0} ({1}) ko email likha hua hai. Send aap dabao."),
    ("Who should get the message on {0}?", "{0} pe kisko message bhejna hai?"),
    ("I do not know {0}'s {1} {2}. Say once: 'save {3}'s {4} as <{5}>', then send again.",
     "Mujhe {0} ka {1} {2} nahi pata. Ek baar bolo: '{3} ka {4} <{5}> hai', phir dobara bhejo."),
    ("What should I send to {0} on {1}?", "{0} ko {1} pe kya bhejna hai?"),
    ("{0} messages work only in the phone app.", "{0} messages sirf phone wale app mein chalte hain."),
    ("The {0} app is not installed on this phone, so nothing was sent.",
     "{0} app is phone par install nahi hai, isliye message nahi bheja."),
    ("To message on {0}, 'Lazey phone control' must be on. Tap 'Turn on phone control', switch it on, then say it "
     "again.",
     "{0} pe message ke liye 'Lazey phone control' on karna hoga. Tap 'Turn on phone control', switch it on, then say "
     "it again."),
    ("Cannot send this: {0}", "Ye nahi bhej sakta: {0}"),
    ('Proposal: send on {0} to the chat named "{1}":', 'Proposal: {0} pe "{1}" naam ki chat ko bhejna hai:'),
    ("Steps: open {0} messages, open that chat (if several match, I ask you), type, press Send, check it was sent.",
     "Steps: {0} messages kholna, wo chat kholna (kai milein to aapse poochhunga), type karna, Send dabana, check "
     "karna ki message gaya."),
    ("Proposal: send on {0} to {1} ({2}):", "Proposal: {0} pe {1} ({2}) ko bhejna hai:"),
    ("Steps: open the chat, check it is {0}, type, press Send, check it was sent.",
     "Steps: chat kholna, check karna ki ye {0} hai, type karna, Send dabana, check karna ki message gaya."),
    ("({0} is not tested on a phone yet.)", "({0} abhi kisi phone par test nahi hua.)"),
    # "how do I message on X?" (pa/messaging.py how_to)
    ("No messaging app was found on this phone.", "Is phone par koi messaging app nahi mila."),
    ("These messaging apps are on this phone:", "Is phone par ye messaging apps hain:"),
    ("Ask about any app, e.g. 'how do I message on instagram'.",
     "Kisi bhi app ke baare mein pucho, jaise 'instagram pe message kaise bheju'."),
    ("{0} is not installed on this phone.", "{0} is phone par install nahi hai."),
    ("{0} is on the phone, but Lazey cannot send messages with {1}. {2}",
     "{0} phone par hai, par Lazey {1} se message nahi bhej sakta. {2}"),
    ("To send messages with {0}:", "{0} se message bhejne ke liye:"),
    ("[MISSING] {0} (optional)", "[BAAKI] {0} (optional)"),
    ("[OK] {0} (optional)", "[OK] {0} (optional)"),
    ("[MISSING] {0}", "[BAAKI] {0}"),
    ("[OK] {0}", "[OK] {0}"),
    # what each messaging app needs (Settings > Customize shows them in English; the chat follows the task)
    ("Permission to read contacts (to find a number by name)",
     "Contacts padhne ki permission (naam se number dhoondhne ke liye)"),
    ("Permission to send SMS", "SMS bhejne ki permission"),
    ("WhatsApp auto-send (Lazey presses Send; when off, you press Send)",
     "WhatsApp auto-send (Send Lazey dabata hai; band ho to aap dabate ho)"),
    ("Lazey phone control ON (to open the chat, type and press Send)",
     "Lazey phone control ON (chat kholne, type karne aur Send dabane ke liye)"),
    ("At least one saved {0} (now {1})", "Kam se kam ek saved {0} (abhi {1})"),
    ("At least one saved email address (now {0})", "Kam se kam ek saved email address (abhi {0})"),
    ("Messenger app installed (Facebook messages are sent with Messenger)",
     "Messenger app installed (Facebook messages Messenger se jaate hain)"),
    ("Everything is ready.", "Sab ready hai."),
    ("Fix the rest in Settings > Customize > {0} with 'Fix this'.",
     "Baaki cheezein Settings > Customize > {0} mein 'Fix this' se theek karo."),
    ("Say it like: {0}", "Aise bolo: {0}"),
    ("(This flow was not tested on a real phone.)", "(Ye flow asli phone par test nahi hua.)"),
    ("Only people you already have a LinkedIn chat with (in your Messaging list) can be messaged.",
     "Sirf unhe message ja sakta hai jinke saath LinkedIn par pehle se chat hai (Messaging list mein)."),
    ("Only people already in your Discord DM list (near the top) can be messaged.",
     "Sirf unhe message ja sakta hai jo Discord DM list mein (upar) hain."),
    ("Truecaller messages are SMS, so Lazey sends them as SMS.",
     "Truecaller ke messages SMS hote hain, isliye Lazey unhe SMS se bhejta hai."),
    ("Lazey opens Slack and looks for the chat by name on the first screen (open DMs / recent chats).",
     "Lazey Slack kholkar pehli screen par naam se chat dhoondhta hai (open DMs / recent chats)."),
    ("Lazey opens Google Chat and looks for the chat by name on the first screen.",
     "Lazey Google Chat kholkar pehli screen par naam se chat dhoondhta hai."),
    ("Save the person's number with country code, e.g. +919876543210.",
     "Number country code ke saath save karo, jaise +919876543210."),
    # app messages (main.py)
    ("Sure? Tap 'Reset Lazey' again.", "Pakka? Dobara 'Reset Lazey' dabao."),
    ("Reset failed: {0}", "Reset nahi ho paya: {0}"),
    ("Reset done ({0} moved aside). Lazey is starting again...",
     "Reset ho gaya ({0} alag rakhe gaye). Lazey phir se shuru ho raha hai..."),
    ("Lazey is ready.", "Lazey ready hai."),
    ("Lazey cannot open its encrypted data ({0}). The old data cannot be recovered. Tap 'Reset Lazey' to start fresh "
     "(the old files are not deleted, they are moved aside).",
     "Lazey apna encrypted data nahi khol pa raha ({0}). Purana data wapas nahi aa sakta. 'Reset Lazey' dabao to naya "
     "shuru hoga (purani files hatayi nahi jaati, alag rakh di jaati hain)."),
    ("Startup failed: {0}", "Startup nahi hua: {0}"),
    ("Could not restart daily messages: {0}", "Daily messages dobara shuru nahi ho paye: {0}"),
    ("Calendar permission was not given: availability will not be checked (the event screen can still open).",
     "Calendar permission nahi mili: khaali time check nahi hoga (event screen phir bhi khul sakti hai)."),
    ("Cannot ask for permissions on this device.", "Is device par permission nahi maang sakta."),
    ("Permission granted. Please say your request again.", "Permission mil gayi. Ab wahi dobara bolo."),
    ("Still missing: {0}. Without it this cannot be done; nothing changed.",
     "Abhi bhi nahi mili: {0}. Iske bina ye nahi ho sakta; kuch nahi badla."),
    ("Permission was not given, so this cannot be done. Nothing changed.",
     "Permission nahi mili, isliye ye nahi ho sakta. Kuch nahi badla."),
    ("Error: {0}", "Error: {0}"),
    ("No key was found for encrypted storage, so the app cannot open your data (there is no plaintext fallback). "
     "Detail: {0}",
     "Encrypted storage ki key nahi mili, isliye app aapka data nahi khol sakta (bina encryption ka koi raasta nahi "
     "hai). Detail: {0}"),
    ("Asking for the permission needed for {0}.", "{0} ke liye permission maang raha hoon."),
    ("Voice input works only on the phone.", "Voice input sirf phone par chalta hai."),
    ("Microphone permission was not given, so voice input is off. You can still type.",
     "Mic ki permission nahi mili, isliye voice input band hai. Aap type kar sakte ho."),
    ("I did not hear anything. Tap the mic and try again.", "Mujhe kuch sunai nahi diya. Mic dabakar dobara bolo."),
    ("The voice pack is still loading. Try again in a moment.",
     "Voice pack abhi load ho raha hai. Thodi der mein dobara try karo."),
    ("Could not use the microphone. Another app may be using it; close it and try again.",
     "Mic use nahi ho paya. Shayad koi aur app mic use kar raha hai; use band karke dobara try karo."),
    ("Lazey's voice pack could not load ({0}). Type instead, or pick 'Phone speech' in Voice.",
     "Lazey ka voice pack load nahi hua ({0}). Type karo, ya Voice mein 'Phone speech' chuno."),
    ("Tell me the {0} of each person you want to message, once. For example:",
     "Jinhe message bhejna hai unka {0} ek baar bata do. Jaise:"),
    ("Could not open the Play Store. Install '{0}' yourself.", "Play Store nahi khula. '{0}' khud install karo."),
    ("In the screen that opens, tap '{0} phone control' (under 'Downloaded services') and switch it on.",
     "Jo screen khulegi usme '{0} phone control' ('Downloaded services' ke neeche) tap karke on karo."),
    ("If it is greyed out ('Restricted setting'): open Settings > Apps > {0}, tap the 3 dots at the top right, choose "
     "'Allow restricted settings', then try again.",
     "Agar wo grey hai ('Restricted setting'): Settings > Apps > {0} kholo, upar daayein 3 dots dabao, 'Allow "
     "restricted settings' chuno, phir dobara try karo."),
    ("It only runs the steps you approve, never types into password fields, and stops after 90 seconds.",
     "Ye sirf wahi steps chalata hai jo aap approve karo, password fields mein kabhi type nahi karta, aur 90 second "
     "baad ruk jata hai."),
    ("To let me press Send in WhatsApp: in the screen that opens, tap '{0} auto-send' (under 'Downloaded services') "
     "and switch it on.",
     "WhatsApp mein Send mujhse dabwana hai to: jo screen khulegi usme '{0} auto-send' ('Downloaded services' ke "
     "neeche) tap karke on karo."),
    ("It only acts for 20 seconds after I open a chat, and only on the exact message I typed.",
     "Ye chat kholne ke baad sirf 20 second tak, aur sirf mere type kiye hue message par hi kaam karta hai."),
    ("Opening Settings at '{0} phone control': tap it to switch it off or on.",
     "Settings mein '{0} phone control' khol raha hoon: on/off karne ke liye use tap karo."),
    ("Could not open Settings. Open Settings > Accessibility > {0} phone control yourself.",
     "Settings nahi khula. Settings > Accessibility > {0} phone control khud kholo."),
    ("Opening Settings at '{0} auto-send' (under 'Downloaded services'): tap it to switch it off or on.",
     "Settings mein '{0} auto-send' khol raha hoon ('Downloaded services' ke neeche): on/off karne ke liye use tap "
     "karo."),
    ("Could not open Settings. Open Settings > Accessibility > {0} auto-send yourself.",
     "Settings nahi khula. Settings > Accessibility > {0} auto-send khud kholo."),
    ("All data deleted.", "Saara data delete ho gaya."),
]

# phone-control steps on the approval card ("1. Open YouTube"): used only on numbered lines
STEPS = [
    ("Open {0} messages", "{0} messages kholna"),
    ("Open the {0} chat with @{1}", "{0} pe @{1} ki chat kholna"),
    ('Open the chat with "{0}" (asks you if several chats match)',
     '"{0}" ki chat kholna (kai chats milein to aapse poochhega)'),
    ('Check the chat is with "@{0}" (stops here if not)', 'Check karna ki chat "@{0}" ki hai (nahi to yahin ruk jayega)'),
    ("Check the message shows in the chat", "Check karna ki message chat mein dikh raha hai"),
    ('Tap "{0}" (this button does something for real)', '"{0}" pe tap karna (ye button sach mein kuch karega)'),
    ('Tap "{0}"', '"{0}" pe tap karna'),
    ('Type "{0}"', '"{0}" type karna'),
    ('Search for "{0}"', '"{0}" search karna'),
    ("Scroll {0}", "{0} scroll karna"),
    ("Wait {0} seconds", "{0} second rukna"),
    ("Press Enter", "Enter dabana"),
    ("Go back", "Back jaana"),
    ("Go to the home screen", "Home screen pe jaana"),
    ("Show recent apps", "Recent apps dikhana"),
    ("Open notifications", "Notifications kholna"),
    ("Read the screen and tell you what is on it", "Screen padh kar batana ki us par kya hai"),
    ("Open {0}", "{0} kholna"),
]

# Example commands in replies ("Try:", "Say it like:"): both versions are real commands that
# Lazey understands (tests/test_pa.py checks that both sides parse to the same task).
COMMANDS = [
    ("call mummy from sim 1", "sim 1 se mummy ko call karo"),
    ("send hi to neha on whatsapp", "neha ko whatsapp pe hi bhejo"),
    ("set an alarm for 6 am", "subah 6 baje ka alarm lagao"),
    ("set a timer for 10 minutes", "10 minute ka timer lagao"),
    ("remind me at 6 pm to drink water", "shaam 6 baje yaad dilana ki paani peena hai"),
    ("show yesterday's photos", "kal ki photos dikhao"),
    ("open whatsapp", "whatsapp kholo"),
    ("how much battery is left", "battery kitni hai"),
    ("what is the plan for today", "aaj ka plan kya hai"),
    ("remember that I like to work in the morning", "Yaad rakho mujhe subah kaam karna pasand hai"),
    ("find 45 minutes tomorrow to work on the project", "kal project par 45 minutes kaam karne ka time nikalo"),
    ("send good morning to mummy every day at 8 am", "har subah 8 baje mummy ko good morning message karo"),
    ("what time is it", "kitne baje hain"),
    ("send hi to rahul on whatsapp", "rahul ko whatsapp pe hi bhejo"),
    ("send sms to rahul saying I am late", "rahul ko sms karo ki main late hoon"),
    ("send hi to rahul on instagram", "rahul ko instagram pe hi bhejo"),
    ("send hi to sarita sheoran on linkedin", "sarita sheoran ko linkedin pe hi bhejo"),
    ("send hi to rahul king on discord", "rahul king ko discord pe hi bhejo"),
    ("send hi to rahul sharma on slack", "rahul sharma ko slack pe hi bhejo"),
    ("send hi to rahul sharma on google chat", "rahul sharma ko google chat pe hi bhejo"),
    ("save rahul's instagram as rahul_23", "rahul ka instagram username rahul_23 hai"),
    ("save rahul's messenger as rahul.sharma", "rahul ka messenger username rahul.sharma hai"),
    ("send hi to rahul on messenger", "rahul ko messenger pe hi bhejo"),
    ("save rahul's snapchat as rahul.snap", "rahul ka snapchat username rahul.snap hai"),
    ("send hi to rahul on snapchat", "rahul ko snapchat pe hi bhejo"),
    ("save rahul's email as rahul@gmail.com", "rahul ka email rahul@gmail.com hai"),
    ("email rahul saying meeting at 5", "rahul ko mail karo ki meeting 5 baje hai"),
    ("save rahul's telegram as rahul_k23", "rahul ka telegram username rahul_k23 hai"),
    ("send hi to rahul on telegram", "rahul ko telegram pe hi bhejo"),
    ("save rahul's signal as +919876543210", "rahul ka signal +919876543210 hai"),
    ("send hi to rahul on signal", "rahul ko signal pe hi bhejo"),
    ("save rahul's twitter as rahul", "rahul ka twitter username rahul hai"),
    ("send hi to rahul on twitter", "rahul ko twitter pe hi bhejo"),
    ("save rahul's teams as rahul@company.com", "rahul ka teams rahul@company.com hai"),
    ("send hi to rahul on microsoft teams", "rahul ko microsoft teams pe hi bhejo"),
]
# replies whose part is an example command: that part follows the reply language too
_COMMAND_SLOTS = ("Say it like: {0}", "Aise bolo: {0}")

# single words/phrases inside a reply (a day, a range) -> Hinglish
_HI_WORD = {"today": "aaj", "tomorrow": "kal", "yesterday": "kal", "day": "din", "every day": "har din",
            "last 7 days": "pichhle 7 din", "last 30 days": "pichhle 30 din", "voice": "voice", "video": "video",
            "none yet": "abhi koi nahi"}

_SPEC = re.compile(r"\{(\d+)\}")
_QUOTES = "\"'"


def _compile(template):
    """'Opening {0}.' -> (regex, length of the fixed text). A part never spans lines."""
    out, pos, seen, lit = [], 0, set(), 0
    for m in _SPEC.finditer(template):
        literal = template[pos:m.start()]
        out.append(re.escape(literal))
        lit += len(literal.strip())
        n = m.group(1)
        out.append("(?P=p%s)" % n if n in seen else "(?P<p%s>[^\n]*?)" % n)
        seen.add(n)
        pos = m.end()
    out.append(re.escape(template[pos:]))
    lit += len(template[pos:].strip())
    return re.compile("".join(out)), lit


def _table(pairs):
    table = {"en": [], "hi": []}   # target language -> [(regex, target template, fixed length)]
    for en, hi in pairs:
        rx_en, lit_en = _compile(en)
        rx_hi, lit_hi = _compile(hi)
        table["hi"] += [(rx_en, hi, lit_en), (rx_hi, hi, lit_hi)]   # the second: already Hinglish, keep it
        table["en"] += [(rx_hi, en, lit_hi), (rx_en, en, lit_en)]
    for lang in table:
        table[lang].sort(key=lambda t: -t[2])     # most specific (most fixed text) first
    return table


_TABLE = _table(PAIRS)
_STEPS = _table(STEPS)
_CMD = {}
for _en, _hi in COMMANDS:
    _CMD[("hi", _en.lower())] = _hi
    _CMD[("en", _hi.lower())] = _en
_PREFIX = re.compile(r"^(\s*(?:\d+\.|-|•)\s+|Proposal:\s+)(.+)$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"'])")
_SPLITS = re.compile(r"[.!?]\s+[A-Z]")


def command(example, lang):
    """An example command in the other language, if there is one ("battery kitni hai" <-> ...)."""
    return _CMD.get((lang, (example or "").strip().lower()), example)


def _piece(value, template, start, end, lang, depth):
    """A part inside a reply. Quoted parts (message texts, names) are never changed; others only
    when they are a whole known phrase (a reason, a day word)."""
    if not value or depth > 2:
        return value
    if (start > 0 and template[start - 1] in _QUOTES) or (end < len(template) and template[end] in _QUOTES):
        return value
    word = value.strip().lower()
    if lang == "hi" and word in _HI_WORD:
        return value[:len(value) - len(value.lstrip())] + _HI_WORD[word]
    if len(word.split()) < 2:
        return value
    lead, tail = value[:len(value) - len(value.lstrip())], value[len(value.rstrip()):]
    done = _match(value.strip(), lang, _TABLE, depth + 1)
    return lead + done + tail if done is not None else value


def _match(text, lang, table=_TABLE, depth=0):
    for rx, target, _ in table[lang]:
        m = rx.fullmatch(text)
        if not m:
            continue
        groups = m.groupdict()
        if any(_SPLITS.search(g or "") for g in groups.values()):
            continue   # a part would swallow a whole sentence: not this pair
        out, pos = [], 0
        for sm in _SPEC.finditer(target):
            out.append(target[pos:sm.start()])
            value = groups.get("p" + sm.group(1), "")
            if target in _COMMAND_SLOTS:   # "save ... as ...  ->  send hi to ..." : each command
                out.append("  ->  ".join(command(c, lang) for c in value.split("  ->  ")))
            else:
                out.append(_piece(value, target, sm.start(), sm.end(), lang, depth))
            pos = sm.end()
        out.append(target[pos:])
        return "".join(out)
    return None


def _line(line, lang):
    if not line.strip():
        return line
    done = _match(line, lang)
    if done is not None:
        return done
    p = _PREFIX.match(line)
    if p:
        done = _match(p.group(2), lang)
        if done is None and re.match(r"\s*\d+\.", p.group(1)):
            done = _match(p.group(2), lang, _STEPS)
        if done is not None:
            return p.group(1) + done
    parts = _SENTENCE.split(line)
    if len(parts) > 1:
        return " ".join(_match(x, lang) or x for x in parts)
    return line


def _capital(src, out):
    """'aaj ka plan' -> 'Aaj ka plan' when the original line started with a capital letter."""
    if src[:1].isupper() and out[:1].islower():
        return out[0].upper() + out[1:]
    return out


def localize(text, lang):
    """The reply in `lang` ("en" or "hi"), line by line. Unknown parts stay as they are."""
    if not text or lang not in ("en", "hi"):
        return text
    return "\n".join(_capital(line, _line(line, lang)) for line in text.split("\n"))
