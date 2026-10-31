# Book sources

Books are included in `data/books/`; no book download is needed to run the project.
The links below come from the Project Gutenberg notices inside the supplied files.

| Book title (filename without `.txt`) | Project Gutenberg eBook |
|---|---|
| Computers—The Machines We Think With | [72572](https://www.gutenberg.org/ebooks/72572) |
| Giant Brains; or, Machines That Think | [68991](https://www.gutenberg.org/ebooks/68991) |
| On-Line Data-Acquisition Systems in Nuclear Physics, 1969 | [42613](https://www.gutenberg.org/ebooks/42613) |
| Origin of Modern Calculating Machines | [69386](https://www.gutenberg.org/ebooks/69386) |
| Passages from the Life of a Philosopher | [57532](https://www.gutenberg.org/ebooks/57532) |
| Sketch of the Analytical Engine Invented by Charles Babbage, Esq | [75107](https://www.gutenberg.org/ebooks/75107) |
| The Calculating Engine | [71292](https://www.gutenberg.org/ebooks/71292) |
| Hackers, Heroes of the Computer Revolution. Chapters 1 and 2 | [729](https://www.gutenberg.org/ebooks/729) |
| Workshop on Electronic Texts - Proceedings, 9-10 June 1992 | [53](https://www.gutenberg.org/ebooks/53) |
| The Internet and Languages [around the year 2000] | [30422](https://www.gutenberg.org/ebooks/30422) |
| Multilingualism on the Web | [27028](https://www.gutenberg.org/ebooks/27028) |
| A History of EBooks | [29801](https://www.gutenberg.org/ebooks/29801) |
| Entretiens - Interviews - Entrevistas | [27035](https://www.gutenberg.org/ebooks/27035) |
| Encyclopaedia Britannica, 11th Edition - Jevons, Stanley to Joint | [41055](https://www.gutenberg.org/ebooks/41055) |
| The Principles of Science - A Treatise on Logic and Scientific Method | [74864](https://www.gutenberg.org/ebooks/74864) |

Gutenberg notices and license text remain inside each book. The Analytical Engine
text was converted from HTML; image descriptions remain, but visual equations may
be incomplete.

Ingestion uses filenames as book titles and hashes file contents to detect changes.
No book manifest is needed. Extracted years must be supported by the quoted passage;
unknown event years remain null.

*Hackers* contains only Chapters 1 and 2, as supplied by Gutenberg, and retains its
copyright notice. The workshop filename replaces the title colon with a hyphen for
filename compatibility; its text is unchanged.

Filenames normalize slashes, quotation marks, and subtitle punctuation for file-system
compatibility. Downloaded book contents are unchanged.
