"use client";

import DataTable from "@/app/components/explorer/DataTable";

interface BoringGenericDisplayProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: { [key: string]: any }[];
}

const BoringGenericDisplay: React.FC<BoringGenericDisplayProps> = ({
  payload,
}) => {
  return (
    <div className="w-full flex flex-col justify-start items-start">
      <DataTable
        data={payload}
        header={payload[0]}
        stickyHeaders={true}
        maxHeight="30vh"
      />
    </div>
  );
};

export default BoringGenericDisplay;
