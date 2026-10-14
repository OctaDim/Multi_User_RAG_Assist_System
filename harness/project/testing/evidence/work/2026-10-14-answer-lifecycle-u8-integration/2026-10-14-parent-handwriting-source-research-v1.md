# U8 genuine handwriting source research

Date: 2026-10-14. Parent read-only web research while the U8 implementer owns production/test authoring. No images downloaded, models evaluated, or corpus files changed by this research. These are candidate inputs, not acceptance results.

## Belarusian

[Kupala autograph PDF metadata](https://commons.wikimedia.org/wiki/File:%D0%90_%D1%85%D1%82%D0%BE_%D1%82%D0%B0%D0%BC_%D1%96%D0%B4%D0%B7%D0%B5_%D0%B0%D1%9E%D1%82%D0%BE%D0%B3%D1%80%D0%B0%D1%84.pdf) describes Yanka Kupala's 1908 handwritten poem and attributes the scan to the [National Library original](http://content.nlb.by/content/dav/nlb/portal/content/File/Portal/InfoResoursy/Kupala_and_Kolas/documents/first_work_Kupala/5.pdf).

Indexed metadata: one page, 592208 bytes, 5362 × 7193; uploaded 2012-11-24 20:22; SHA-1 `18ff5349854b7ec35809d372340724754aef003c`. The title contains Belarusian і; presence and legibility of ў in the actual raster require visual verification. The web tool returned metadata through search but could not open the Commons PDF page or National Library HTTPS URL. No SHA-256 or recognition result was established here. The receiving implementer must validate original bytes, handwriting, independent expected transcription, and any image transformation before using this input.

## German

The [Fachhochschule Südwestfalen dataset](https://huggingface.co/datasets/fhswf/german_handwriting) describes genuine handwriting from 15 people, collected from school/university transcripts. Observed repository revision: `f08067881aafb8ad50f0ca14c1e57314438b79a2`. Dataset metadata identifies AFL-3.0; the receiver must retain the applicable source notice.

Viewer row 5 has an independent sentence transcription including ü. Its image asset path is `assets/fhswf/german_handwriting/--/f08067881aafb8ad50f0ca14c1e57314438b79a2/--/default/train/5/image/image.jpg`; viewer URLs are signed and expire. Resolve a current URL through the dataset viewer API, then record revision, row, original SHA-256, and independent transcription. This can avoid downloading the entire 1.8 GB dataset. Actual image bytes were not inspected here.

The [DHSD authors' repository](https://github.com/nauman-riaz/DHSD) provides genuine handwritten geographic names by 37 writers, annotations in `data.csv`, and `checksums.sha256`, with CC BY 4.0 metadata. Images are word crops, 256 × 64. This offers a separate detector/crop input but cannot establish sentence/page recognition by itself. No repository revision or image SHA-256 was established here.

## Russian

The [IDP-forms authors' repository](https://github.com/ai-forever/htr_datasets/tree/main/IDP-forms) describes handwriting collected on forms and provides individual `august.png` and `form.png` examples. Its main image archive has independent text annotations. Verify the individual raster and its expected text before using an example; filename alone is not transcription proof.

[HWR200](https://huggingface.co/datasets/AntiplagiatCompany/HWR200) describes real handwriting by 200 writers, with scanned and photographed variants and Apache-2.0 metadata. Its image archives are several GB each; no archive was downloaded.

The [School Notebooks authors' dataset](https://huggingface.co/datasets/ai-forever/school_notebooks_RU) describes real Russian handwritten pages and COCO line polygons with independent transcriptions. Its total size is about 3.06 GB and its legacy dataset viewer is disabled. No loader code was executed or image archive downloaded.

All candidates were passed to the U8 implementer. None closes G4 without the actual issuer/publisher/OCR integration and its measured result.
