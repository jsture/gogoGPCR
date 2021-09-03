import hail as hl
from pathlib import Path
from typing import Optional, Union, List


def import_mt(
    vcf_files: Union[str, List[str]],
    mapping: dict,
) -> hl.matrixtable.MatrixTable:
    """Import VCF file or list of VCF files as MatrixTable

    Parameters
    ----------
    vcf_files : Union[str, list[str]]
        VCF or list of VCF files
    drop_samples : bool, optional
        Drop sample information and return only variant info, by default False

    Returns
    -------
    hl.matrixtable.MatrixTable
        Raw MatrixTable of all samples and variants, very large. GRCh38 as reference.
    """

    region = [
        hl.parse_locus_interval(
            f"[chr{mapping['GRCh38_region']}:{mapping['GRCh38_start']}-chr{mapping['GRCh38_region']}:{mapping['GRCh38_end']}]"
        )
    ]

    mts = hl.import_gvcfs(
        vcf_files,
        partitions=region,
        reference_genome="GRCh38",
        array_elements_required=False,
    )

    if len(mts) == 1:
        return mts[0]
    else:
        return hl.MatrixTable.union_rows(*mts)
    

def downsample_mt(
    mt: hl.matrixtable.MatrixTable,
    prob: Optional[float] = None,
    seed = 42,
) -> hl.matrixtable.MatrixTable:
    """Reduce number of samples in MatrixTable

    Parameters
    ----------
    mt : hl.matrixtable.MatrixTable
        MatrixTable with samples as columns
    prob : Optional[float], optional
        Fraction of samples to keep, 1 / 200 results in ~1000 samples, by default None

    Returns
    -------
    hl.matrixtable.MatrixTable
        Downsampled MatrixTable
    """

    if prob is not None:
        return mt.sample_cols(p=prob, seed = seed)
    else:
        return mt
    
def interval_qc_mt(
    mt: hl.matrixtable.MatrixTable,
    mapping: dict,
    intervals: Union[str, Path],
) -> hl.matrixtable.MatrixTable:
    """Filter to only Target region used by the WES capture experiment

    Parameters
    ----------
    mt : hl.matrixtable.MatrixTable
        MatrixTable
    intervals : str
        .BED file of targeted capture regions which meet quality standards

    Returns
    -------
    hl.matrixtable.MatrixTable
        MatrixTable filtered to only target regions
    """

    interval_table = hl.import_bed(
        intervals,
        reference_genome="GRCh38",
        filter=f"^(?!(chr{mapping['GRCh38_region']}))",
    )

    mt = mt.filter_rows(hl.is_defined(interval_table[mt.locus]))

    return mt

def hard_sample_filter_mt(
    mt: hl.matrixtable.MatrixTable,
    samples_to_remove: str,
) -> hl.matrixtable.MatrixTable:
    """Filter out samples failing quality control

    Parameters
    ----------
    mt : hl.matrixtable.MatrixTable
        Matrix table with sample information
    samples_to_remove : str
        List of samples to filter out as generated by sample_hard_filter.py
        includes relatedness, sex aneuploidy, outliers etc.

    Returns
    -------
    hl.matrixtable.MatrixTable
        MatrixTable with filtered samples
    """

    ht = hl.import_table(samples_to_remove, no_header=True, key="f0")

    mt = mt.anti_join_cols(ht)

    mt = mt.filter_cols(mt.s.startswith("-"), keep=False)

    return mt


def smart_split_multi_mt(
    mt: hl.matrixtable.MatrixTable, left_aligned=False
) -> hl.matrixtable.MatrixTable:

    mt = mt.key_rows_by("locus", "alleles")

    bi = mt.filter_rows(hl.len(mt.alleles) == 2)
    bi = bi.annotate_rows(a_index=1, was_split=False)
    multi = mt.filter_rows(hl.len(mt.alleles) > 2)
    split = hl.split_multi_hts(multi, left_aligned=left_aligned)
    mt = split.union_rows(bi)

    return mt

def hard_variant_filter_mt(
    mt: hl.matrixtable.MatrixTable,
    min_p_value_hwe: Optional[float],
    min_GQ: Union[float, int, None],
) -> hl.matrixtable.MatrixTable:

    try:
        mt.variant_qc
    except AttributeError:
        print("hard_variant_filter requires variant_qc")

    if min_p_value_hwe is not None:
        mt = mt.filter_rows(
            mt.variant_qc.p_value_hwe < min_p_value_hwe, keep=False
        )

    if min_GQ is not None:
        mt = mt.filter_rows(mt.variant_qc.gq_stats.mean < min_GQ, keep=False)

    return mt

def genotype_filter_mt(
    mt: hl.matrixtable.MatrixTable,
    min_DP: Union[float, int, None],
    min_GQ: Union[float, int, None],
    log_entries_filtered: True,
) -> hl.matrixtable.MatrixTable:

    mt = mt.filter_entries(
        (mt.GT.is_haploid() & (mt.DP > min_DP // 2) & (mt.GQ >= min_GQ))
        | ((mt.GT.is_diploid() & (mt.DP > min_DP) & (mt.GQ >= min_GQ))),
        keep=True,
    )

    if log_entries_filtered:
        mt = mt.compute_entry_filter_stats()

    return mt

def filter_no_carriers(
    mt: hl.matrixtable.MatrixTable,
) -> hl.matrixtable.MatrixTable:

    try:
        mt.variant_qc
    except AttributeError:
        print("filter_no_carriers requires variant_qc")

    mt = mt.filter_rows(mt.variant_qc.n_non_ref == 0, keep=False)

    return mt

def add_varid(mt: hl.MatrixTable) -> hl.MatrixTable:
    """Annotate rows with varid

    Parameters
    ----------
    mt : hl.MatrixTable
        [description]

    Returns
    -------
    hl.MatrixTable
        [description]
    """

    mt = mt.annotate_rows(
        varid=hl.delimit(
            [
                mt.locus.contig,
                hl.str(mt.locus.position),
                mt.alleles[0],
                mt.alleles[1],
            ],
            ":",
        )
    )

    return mt