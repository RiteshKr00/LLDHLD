# Notification System

> **Is problem ka star pattern: Observer (pub-sub).**

---

## Problem kya hai

App mein kuch hua — kisi ne comment kiya, order ship hua, payment aaya. Ab **sahi logon ko**, **sahi
channel pe** (email/SMS/push/in-app), **sahi message** bhejo. Aur agar bhejne mein fail ho jaye toh
dobara try karo.

---

## Pehla instinct

```python
def post_comment(comment):
    save_comment(comment)
    email_service.send(comment.post.owner, f"{comment.author} ne comment kiya")
    sms_service.send(comment.post.owner, f"{comment.author} ne comment kiya")
    push_service.send(comment.post.owner, f"{comment.author} ne comment kiya")
    analytics.track("comment_posted", comment)
```

Ab thoda ruk ke socho — **`post_comment` ko SMTP ke baare mein pata kyun hai?** Yeh function
**comments** ke baare mein hai. Usko email se kya lena-dena?

Aur paanch aur dikkatein:

**1. "Slack pe bhi alert bhejo."** → `post_comment` edit karo.
**"Badge counter bhi update karo."** → phir edit.
Har naye feature ke liye **chalte hue code ko wapas kholna** pad raha hai (Open/Closed violation).

**2. "Post comment ka test likho."** → pehle 4 services mock karo. 😩

**3. SMS provider slow hai (3 second).**
→ **Comment post karne mein 3 second lagenge.** User uss cheez ka wait kar raha hai jo usne maangi
hi nahi thi.

**4. Email ne exception phenka** → `sms`, `push`, `analytics` **kabhi chale hi nahi**. Ek toota hua
cheez ne baaki sabko le dooba.

**5.** Kal ko orders, payments, signups — sab jagah yehi 4 lines copy-paste hongi.

---

## Flip: bulao mat, **announce** karo

Kya ho agar `post_comment` bas **elaan** kar de ki kuch hua, aur usko farak hi na pade ki kaun sun
raha hai?

```python
def post_comment(comment):
    save_comment(comment)
    event_bus.publish(Event(COMMENT_POSTED, {...}))     # "bhai, yeh hua hai." Bas. Khatam.
```

**Bas itna hi.** Usko nahi pata ki **zero** log sun rahe hain ya **pachaas**.

Aur **kahin aur**, app start hote waqt:

```python
event_bus.subscribe(COMMENT_POSTED, notification_service)
event_bus.subscribe(COMMENT_POSTED, analytics_service)
event_bus.subscribe(COMMENT_POSTED, badge_counter)      # <- baad mein add kiya,
                                                        #    post_comment chhua tak nahi
```

**Yehi Observer hai.** Publisher elaan karta hai, listeners khud register hote hain. Dono ek dusre ko
jaante hi nahi.

> **YouTube wala example:** creator video daalta hai. Woh 20 lakh logon ko **ek-ek karke phone nahi
> karta**. Woh bas publish karta hai — subscribers ko notification isliye milta hai kyunki unhone
> **subscribe kiya tha**. 20 lakhva subscriber aane se creator ka upload karne ka tarika nahi badalta.

---

## EventBus — poora pattern 10 line mein

```python
class EventBus:
    def __init__(self):
        self._subs: dict[EventType, list[Subscriber]] = {}

    def subscribe(self, event_type, subscriber):
        self._subs.setdefault(event_type, []).append(subscriber)

    def publish(self, event):
        for sub in self._subs.get(event.event_type, []):
            sub.handle(event)          # <- bus ko BILKUL nahi pata handle() kya karta hai
```

Woh aakhri line hi poora pattern hai. Bus sirf `handle(event)` bulata hai — bas. Email? Analytics?
Usko koi matlab nahi.

Aur `Subscriber` sirf itna hai:
```python
class Subscriber(ABC):
    @abstractmethod
    def handle(self, event: Event) -> None: ...
```

**Yeh ABC hi woh cheez hai jo bus ko anjaan rehne deti hai.** Iske bina "subscriber list" kis cheez ki
list hai? Kisi cheez ki nahi.

---

## Strategy vs Observer — dono ek jaise dikhte hain

Dono mein ek ABC hota hai, ek method. Farak **use** ka hai:

| | Strategy | Observer |
|---|---|---|
| Kitne? | **ek** algorithm chuno | **sabko** notify karo |
| Maqsad | *kaise* hota hai woh badalna | *kaun react karta hai* usko alag karna |
| Example | `ShortCodeGenerator` — ek generator chuna | `EventBus` — sab subscribers ko bheja |

---

## Channel — enum bhi, Strategy bhi (dono!)

Yeh interesting nuance hai. Ab tak test tha "data ya behaviour?" — yahan **dono** chahiye:

**`ChannelType` (enum)** — `EMAIL, SMS, PUSH, IN_APP`
Preferences mein use hota hai: *"mujhe EMAIL aur PUSH pe bhejo"*. Yahan channel bas ek **label** hai
jo tum store karte ho, compare karte ho. → **Data**

**`NotificationChannel` (Strategy ABC)** — `EmailChannel.send()`, `SmsChannel.send()`
Yahan channel ka matlab hai **asli bhejne ka kaam** — aur email bhejna SMS bhejne se bilkul alag
kaam hai. → **Behaviour**

Dono ko jodta hai ek dict:
```python
self.channels: dict[ChannelType, NotificationChannel] = {
    ChannelType.EMAIL: EmailChannel(),
    ChannelType.SMS:   SmsChannel(),
    ...
}
```

> **Seekh:** data-vs-behaviour hamesha "ya toh yeh, ya woh" nahi hota. Kabhi-kabhi tumhe **label bhi
> chahiye aur implementation bhi** — aur beech mein ek lookup.

---

## Do layers — inko mat milao

Yeh is problem ka structural insight hai:

```
LAYER 1 — decoupling (Observer)
    EventBus  →  Subscriber
    Bus ka kaam sirf itna: publish pe sab subscribers ka handle() bulao. Bas.

LAYER 2 — notification pipeline
    recipients dhoondho → preferences dekho → message banao → bhejo → retry karo
    Yeh normal orchestration hai, jo ek particular subscriber ke andar chalta hai
```

**`NotificationService` dono ko jodta hai** — woh `Subscriber` **implement** karti hai (layer 1) aur
pipeline **own** karti hai (layer 2). Bus ko kabhi pata nahi chalta ki notifications naam ki koi
cheez hai.

---

## Pipeline — ek asli example se

**Event:** `COMMENT_POSTED` — Bob ne Alice ki photo pe comment kiya.

**Step 1 — kisko batana hai?**
Event mein likha hai *kya hua*, *kisko batana hai* nahi. Toh nikaalo: photo ka owner → **Alice**.
*(Yeh clarification #3 tha — system khud recipients nikaalta hai, publisher nahi batata.)*

**Step 2 — Alice ko kaise chahiye?**
Uski preferences dekho `COMMENT_POSTED` ke liye → `{PUSH, IN_APP}`. Usne SMS band kar rakha hai.
Toh **2 notifications** jaayenge, 4 nahi.

**Step 3 — message kya likhna hai?**
Template: `"{author} ne aapki photo pe comment kiya"` + event data → *"Bob ne aapki photo pe comment kiya"*

**Step 4 — bhejo, har channel alag-alag:**
```python
for channel_type in wanted:
    channel = self.channels[channel_type]           # label -> behaviour
    try:
        channel.send(Notification(user, channel_type, content))
    except Exception:
        self._schedule_retry(...)                    # <- YEH try/except hi BULKHEAD hai
                                                     #    mara hua SMS, PUSH ko nahi rok sakta
```

**Step 5 — fail hue ko retry karo** backoff ke saath.

> **Dhyan do:** tumhare do NFRs yahan **ek-ek line ke code** ban gaye:
> - **bulkhead** = loop ke **andar** wala `try/except`
> - **low latency** = publish bina wait kiye return kar deta hai

---

## Concurrency ka trap

Subscriber list **shared mutable state** hai. Agar publish chal raha ho aur usi waqt koi subscribe
kare:

```
RuntimeError: list changed size during iteration
```

Python list ko iterate karte waqt modify nahi karne deta. **Fix:** copy pe iterate karo —
`for sub in list(self._subs.get(...)):`

---

## HLD mein kya badalta hai

Yeh natural pair hai **"fan-out at scale"** ke saath:
- In-process `EventBus` → **Kafka** (services alag machines pe hain)
- Retry → **DLQ** (Dead Letter Queue) — baar-baar fail hone wale message ko alag rakho, investigate
  karo, phir replay
- Event kho na jaye → **Outbox pattern** (DB transaction mein event bhi likho, worker use publish kare)
- **Celebrity problem** — 1 crore subscribers wale ko notify karna hai toh fan-out kaise?

---

## Interview line

> *"Trigger karne wale code ko receivers se decouple kiya — woh sirf event publish karta hai, aur
> listeners khud register hote hain. Isse naya notification type add karna kabhi bhi purane code ko
> chhune ki zaroorat nahi banata. Channel dono roop mein hai — preferences mein enum label, delivery
> mein Strategy. Aur har channel ka send apne try/except mein hai, taaki ek dead channel baaki sabko
> na rok de."*
