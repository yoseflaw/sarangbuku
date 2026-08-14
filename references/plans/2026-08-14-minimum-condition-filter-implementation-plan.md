# Minimum Condition Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Temukan condition filter include the selected condition and every better condition.

**Architecture:** Keep the canonical best-to-worst ordering in `BookCopy.Condition.choices`. The discovery view derives the accepted values from that existing order and applies one `condition__in` query; the form clarifies the threshold with `Kondisi minimum`.

**Tech Stack:** Django forms, ORM, templates, and `TestCase`.

## Global Constraints

- Preserve existing discovery eligibility, privacy, filter composition, and fail-closed validation.
- Use natural Indonesian user-facing copy.
- Add no model fields, migrations, dependencies, or new abstraction.

---

### Task 1: Minimum Condition Discovery Filter

**Files:**
- Modify: `books/tests/test_discovery.py:150-216`
- Modify: `books/forms.py:47-49`
- Modify: `books/views.py:70-71`

**Interfaces:**
- Consumes: `BookCopy.Condition.choices`, ordered best to worst as defined in `books/models.py`.
- Produces: `DiscoveryFilterForm.condition` labeled `Kondisi minimum`; discovery results include selected-or-better conditions.

- [ ] **Step 1: Write the failing regression tests**

Add this form assertion to `DiscoveryFilterFormTests`:

```python
    def test_condition_label_describes_minimum_threshold(self):
        form = DiscoveryFilterForm(viewer=self.viewer)

        self.assertEqual(form.fields["condition"].label, "Kondisi minimum")
```

Add this behavior test to `DiscoveryListTests`:

```python
    def test_condition_filter_includes_selected_and_better_but_excludes_worse(self):
        better_book = Book.objects.create(
            title="Buku Lebih Baik",
            authors="Penulis A",
            language="Indonesia",
        )
        worse_book = Book.objects.create(
            title="Buku Lebih Buruk",
            authors="Penulis B",
            language="Indonesia",
        )
        BookCopy.objects.create(
            owner=self.owner,
            book=better_book,
            condition=BookCopy.Condition.LIKE_NEW,
            is_available=True,
        )
        BookCopy.objects.create(
            owner=self.owner,
            book=worse_book,
            condition=BookCopy.Condition.FAIR,
            is_available=True,
        )

        response = self.client.get(
            reverse("books:discover"),
            {"condition": BookCopy.Condition.GOOD},
        )

        self.assertContains(response, "Matilda")
        self.assertContains(response, "Buku Lebih Baik")
        self.assertNotContains(response, "Buku Lebih Buruk")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python manage.py test \
  books.tests.test_discovery.DiscoveryFilterFormTests.test_condition_label_describes_minimum_threshold \
  books.tests.test_discovery.DiscoveryListTests.test_condition_filter_includes_selected_and_better_but_excludes_worse
```

Expected: both tests fail because the label is still `Kondisi` and the exact-match query omits `Buku Lebih Baik`.

- [ ] **Step 3: Implement the minimal threshold behavior**

Change the field label in `books/forms.py`:

```python
    condition = forms.ChoiceField(
        label="Kondisi minimum",
```

Replace the exact query in `books/views.py`:

```python
            if condition := form.cleaned_data["condition"]:
                conditions = [value for value, _ in BookCopy.Condition.choices]
                copies = copies.filter(
                    condition__in=conditions[: conditions.index(condition) + 1]
                )
```

Form validation guarantees `condition` is one of the canonical values before this branch runs.

- [ ] **Step 4: Run focused and discovery tests and verify GREEN**

Run:

```bash
python manage.py test books.tests.test_discovery
```

Expected: all discovery tests pass.

- [ ] **Step 5: Run project verification**

Run:

```bash
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
python -m pip check
git diff --check
```

Expected: every command exits 0; no migration is generated.

- [ ] **Step 6: Commit**

```bash
git add books/forms.py books/views.py books/tests/test_discovery.py
git commit -m "Fix discovery minimum condition filter"
```
