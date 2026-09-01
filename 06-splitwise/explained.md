# Splitwise

> **Is problem ka core:** paisa sambhalna, aur "balance store karoon ya nikaaloon" wala decision.

---

## Problem kya hai

Doston ka group Goa gaya. Alice ne hotel ka ₹1000 diya, Bob ne cab ka ₹400 diya, Carol ne khaane ka
₹600. Ab hisaab karo — kaun kisko kitna de.

Aur **simplify** bhi karo: agar A→B ₹500 aur B→C ₹500 hai, toh seedha A→C ₹500 kar do. Kam
transactions.

---

## Pehla instinct

```python
balances = {}          # user -> float

def add_expense(payer, amount, people):
    share = amount / len(people)
    for p in people:
        balances[p] = balances.get(p, 0) - share
    balances[payer] = balances.get(payer, 0) + amount
```

Chalta hua lagta hai. Ab **paanch** dikkatein:

### 1. `float` mein paisa — kabhi mat karna
```python
>>> 0.1 + 0.2
0.30000000000000004      # 😬
```
Float **binary fractions** hote hain — `0.1` ko exactly represent kar hi nahi sakte (jaise tum ⅓ ko
decimal mein exactly nahi likh sakte). Hazaaron expenses ke baad balance **drift** kar jaayega, aur
tum user ko explain nahi kar paoge ki uske ₹430.0000001 kahan se aaye.

**Fix:** `Decimal` use karo (ya paise ko **integer** mein rakho aur sirf dikhane ke waqt divide karo).

### 2. Paisa gayab ho jaata hai
₹1000, 3 log. Har ek ka hissa = 333.333...
Round karke 333.33 → teeno ka total = **₹999.99**.
**Ek paisa gayab.**

Aur agar upar round karo (333.34 × 3 = ₹1000.02) toh tumne **paisa bana diya** — jo aur bhi bura hai.

### 3. Sirf equal split
"Exact amounts se baanto" ya "percentage se" → yeh function jaanta hi nahi. Rewrite.

### 4. `balances[p] -= share` — race
Do log ek saath expense daal rahe hain → dono ne purana balance padha → ek update **gum**.

### 5. "Main ₹430 kyun de raha hoon?" — jawab hi nahi hai
Tumne sirf **total** store kiya, **kaise aaya woh nahi**. Koi audit trail nahi. User poochega toh
tum kandhe uchka doge.

---

## Fix #1: paisa hamesha exact rehna chahiye

**Invariant yaad rakho: `sum(splits) == total`, hamesha, exactly.**

Tarika:
```python
base = (total / n).quantize(PAISA, rounding=ROUND_DOWN)   # neeche round karo
remainder = total - (base * n)                             # 1000 - 999.99 = 0.01
extra_paise = int(remainder / PAISA)                       # 1 paisa bacha

# pehle `extra_paise` logon ko ek-ek paisa extra
[333.34, 333.33, 333.33]    # total = exactly 1000.00 ✅
```

**Neeche (ROUND_DOWN) kyun round karte hain?** Taaki hum **kam** baantein, aur bacha hua paisa haath
mein rahe — usko baad mein baant sakein. Upar round karoge toh **zyada** baant doge, aur us extra ko
wapas lena impossible hai.

Thoda unequal hai (kisi ko 1 paisa zyada) — par **paisa conserve** hua, aur wahi zaroori hai.

---

## Fix #2: split types → Strategy

"Equal / exact / percentage — aur baad mein aur bhi." Yeh **Strategy ka signal** hai.

```python
class SplitStrategy(ABC):
    def calculate(self, total, participants, params) -> list[Split]: ...

class EqualSplit:        # barabar, paisa redistribute karke
class ExactSplit:        # params hi amounts hain — bas VALIDATE karo ki sum == total
class PercentageSplit:   # params percentages — validate sum == 100, phir wahi rounding
```

Har ek `list[Split]` deta hai. `Split` matlab **ek line item**: `(user, amount)`.

**Ek chhoti si baat samajh lo:** Alice ne ₹900 diya, 3 mein baanta. Toh:
```
Expense(payer=Alice, amount=900, splits=[
    Split(Alice, 300),      # <- Alice bhi apne splits mein hai!
    Split(Bob,   300),
    Split(Carol, 300),
])
```
Alice ne 900 diye, uska apna hissa 300 hai → net **+600**. Yeh apne aap nikal aata hai.

---

## Fix #3 (sabse mazedaar): balance store karo ya nikaalo?

Do raste the:

**Raasta A — store karo:** ek `balance` field rakho, har expense pe `+=` / `-=` karo.
**Raasta B — nikaalo:** balance kabhi store hi mat karo. Poori expense list se **har baar calculate** karo.

Humne **B** chuna. Kyun?

```python
def net_balances(self, expenses, settlements):
    balances = {}
    for exp in expenses:
        balances[exp.payer] += exp.amount            # jisne diya, usko credit
        for split in exp.splits:
            balances[split.user] -= split.amount     # jiska hissa, usse debit
    ...
```

**Ek decision ne teen problem solve kar diye:**

| Problem | Kaise solve hua |
|---|---|
| Race condition (#4) | Expense add karna ab bas **append** hai. `+=` hai hi nahi → race hai hi nahi. **Poore code mein ek bhi lock nahi.** |
| Audit trail (#5) | "₹430 kyun?" → poori list hai, dikha do. Log **hi** jawab hai. |
| Drift | Har baar truth se calculate hota hai, purana galat data reh hi nahi sakta |

> **Yeh baat interview mein bolna:** *"concurrency requirement ko maine **lock se nahi, modelling se**
> solve kiya."* Yeh strictly better hai jab possible ho.

---

## Settlement ke signs — yahan sab phisalte hain

Settlement matlab: Bob ne Alice ko ₹300 de diye, hisaab chukta karne ke liye.

```python
balances[s.payer] += s.amount     # Bob ko PLUS?!
balances[s.payee] -= s.amount     # Alice ko MINUS?!
```

Pehli nazar mein ulta lagta hai. "Bob ne paisa **diya**, toh Bob minus mein jaana chahiye na?"

**Nahi.** Kyunki `balances` tumhara **wallet nahi hai** — woh group ke ledger mein tumhari **position**
hai:
- **Positive** = tumhe paisa milna hai
- **Negative** = tumhe paisa dena hai

Ab dekho:
```
Pehle:  Alice +600 (usko milna hai), Bob -300 (usko dena hai)

Bob ne Alice ko 300 diye:
  Bob:   -300 + 300 =    0     ✅ uska karza khatam (ZERO ki taraf gaya = UPAR)
  Alice: +600 - 300 = +300     ✅ usko itna wapas mil gaya
```

**Karza chukane ka matlab hai zero ki taraf jaana** — aur agar tum negative mein the, toh zero ki
taraf jaana matlab **upar** jaana.

> **Ek aur baat:** "sab balances ka total zero hona chahiye" wala check **sign flip nahi pakadta**.
> Ulta karne pe bhi total zero hi aata hai. Direction alag se sochna padta hai.

---

## Simplify debts — greedy

Balances: `{Alice: +450, Bob: -50, Carol: -250, Dave: -150}`

**Algorithm:**
1. Sabse bada **creditor** (jisko sabse zyada milna hai) aur sabse bada **debtor** (jisko sabse zyada
   dena hai) uthao
2. `min(dono)` transfer karo
3. Kam se kam ek toh **zero** ho hi jayega → usko list se hata do
4. Repeat

Har round mein ek banda nikalta hai → **zyada se zyada n−1 transfers** (naive "sab sabko de" wale
n² ki jagah).

> **Honest baat jo interview mein bolna chahiye:** *"greedy se n−1 aa jaata hai, par yeh **provably
> optimal nahi** hai. Asli minimum nikalne ke liye zero-sum subgroups dhoondhne padte hain — woh
> **subset-sum** hai, matlab **NP-hard**. Greedy standard practical answer hai."*
>
> Apne algorithm ki limitation khud batana — yeh senior signal hai.

---

## HLD mein ulta ho jaata hai (yeh interesting hai)

LLD mein humne "derive karo, store mat karo" chuna — sundar tha. **Par production mein tootta hai:**

5 saal purana group, 20,000 expenses. Har baar balance screen kholne pe **20,000 calculations**. Aur
balance screen hi sabse zyada khulti hai!

**Toh HLD mein wapas materialize karte hain:**
```sql
BEGIN;
  INSERT INTO expenses (...);
  UPDATE balances SET amount = amount + ? WHERE user_id = ?;
COMMIT;
```
- Read ab **O(1)** — ek row
- Race wapas aa gayi — par ab **DB transaction** sambhalta hai
- **Expense log phir bhi source of truth rehta hai** → reconcile job drift theek kar sakta hai

**Dono sahi hain, apne-apne scale pe.** Bolne wali line:
> *"Correctness ke liye derive karta, read performance ke liye materialize — aur log ko source of
> truth rakhta taaki projection verify ho sake."*

### DB atomicity — yeh dhyan se
```sql
-- ❌ GALAT (gap tumhare code mein hai)
SELECT amount FROM balances       -> 666.66
   ...app 666.66 + 300 calculate karta hai...
UPDATE balances SET amount = 966.66
       ^ is beech mein doosra server bhi 666.66 padh sakta hai -> ek update GUM

-- ✅ SAHI (koi gap nahi, DB khud karta hai)
UPDATE balances SET amount = amount + 300 WHERE user_id = ?
       ^ padhna, jodna, likhna — sab DB ke andar EK step mein
```

**Arithmetic SQL statement ke andar karo, apne Python code mein nahi.**

---

## Interview line

> *"Balance ko derive kiya, store nahi — usse race condition aur audit trail dono ek saath solve ho
> gaye, aur poore codebase mein ek bhi lock nahi hai. Paisa `Decimal` mein, aur equal split mein
> neeche round karke bacha hua paisa redistribute kiya taaki `sum(splits) == total` exactly rahe.
> Scale pe main balance materialize karta, par expense log ko source of truth rakh ke."*
